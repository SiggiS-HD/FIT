#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fit_analyze_gui_v4.py — FIT-Auswertung mit Windows-Dialogen (Tkinter)

Version V4:
- Motorenergie wird aus der gemessenen Nachladeenergie (Sonoff) und
  dem Wall→Battery-Wirkungsgrad berechnet.
- GUI fragt: FIT-Datei, Nachladeenergie (kWh), Effizienz (%), Muskeleffizienz (%)
- Berlin-Zeit in CSV & JSON; CSV mit ';' als Separator und ',' als Dezimaltrennzeichen.
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, simpledialog, messagebox
except Exception:
    tk = None

import pandas as pd
from fitparse import FitFile

SEMICIRCLES_TO_DEGREES = 180 / (2**31)
LOCAL_TZ = "Europe/Berlin"


# --- Helper functions ---------------------------------------------------------
def to_float(v) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def semicircles_to_deg(val) -> Optional[float]:
    v = to_float(val)
    if v is None:
        return None
    return v * SEMICIRCLES_TO_DEGREES


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    if None in (lat1, lon1, lat2, lon2):
        return 0.0
    R = 6371000.0
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlmb/2)**2
    return 2*R*math.atan2(math.sqrt(a), math.sqrt(1-a))


def positive_gain(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    diffs = series.diff()
    return float(diffs[diffs > 0].sum(skipna=True) or 0.0)


# --- FIT Parsing --------------------------------------------------------------
def parse_fit_records(fit_path: Path) -> pd.DataFrame:
    fit = FitFile(fit_path.as_posix())
    records = []
    for msg in fit.get_messages("record"):
        data = {d.name: d.value for d in msg}
        ts = data.get("timestamp")
        if isinstance(ts, datetime):
            ts = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)
        rec = {
            "timestamp": ts,
            "latitude_deg": semicircles_to_deg(data.get("position_lat")),
            "longitude_deg": semicircles_to_deg(data.get("position_long")),
            "altitude_m": to_float(data.get("altitude")),
            "speed_m_s": to_float(data.get("speed")),
            "distance_m": to_float(data.get("distance")),
            "heart_rate_bpm": to_float(data.get("heart_rate")),
            "cadence_rpm": to_float(data.get("cadence")),
            "power_w": to_float(data.get("power")),
            "temperature_c": to_float(data.get("temperature")),
        }
        records.append(rec)
    df = pd.DataFrame.from_records(records)
    if not df.empty:
        df = df.sort_values("timestamp").reset_index(drop=True)
        # Distanz rekonstruieren falls leer
        if df["distance_m"].isna().all() or (to_float(df["distance_m"].max(skipna=True)) or 0) == 0:
            dists = [0.0]
            for i in range(1, len(df)):
                d = haversine_m(df.at[i-1, "latitude_deg"], df.at[i-1, "longitude_deg"],
                                df.at[i, "latitude_deg"], df.at[i, "longitude_deg"])
                dists.append(dists[-1] + (d or 0.0))
            df["distance_m"] = dists
        # Geschwindigkeit rekonstruieren
        if df["speed_m_s"].isna().mean() > 0.5:
            dt = df["timestamp"].diff().dt.total_seconds().fillna(0)
            ds = df["distance_m"].diff().fillna(0)
            dt_safe = dt.mask(dt == 0)
            v = (ds / dt_safe).fillna(0.0).astype("float64")
            df["speed_m_s"] = v
        # Höhe interpolieren
        if df["altitude_m"].notna().sum() > 5:
            df["altitude_m"] = df["altitude_m"].interpolate(limit_direction="both")
    return df


def parse_sessions_and_laps(fit_path: Path) -> Dict[str, Any]:
    fit = FitFile(fit_path.as_posix())
    sessions, laps = [], []
    for msg in fit.get_messages("session"):
        sessions.append({d.name: d.value for d in msg})
    for msg in fit.get_messages("lap"):
        laps.append({d.name: d.value for d in msg})
    return {"sessions": sessions, "laps": laps}


def integrate_work_joules(df: pd.DataFrame) -> float:
    if df.empty or df["power_w"].notna().sum() < 2:
        return 0.0
    power = df["power_w"].fillna(0.0).astype(float)
    dt = df["timestamp"].diff().dt.total_seconds().fillna(0.0)
    p_prev = power.shift(1).fillna(0.0)
    work = ((power + p_prev) / 2.0) * dt
    return float(work.sum())


# --- Metrics ------------------------------------------------------------------
def compute_metrics(df: pd.DataFrame, agg: Dict[str, Any],
                    wall_energy_kWh: Optional[float] = None,
                    eff_wall2batt_pct: Optional[float] = None,
                    muscle_eff_pct: Optional[float] = 24.0) -> Dict[str, Any]:
    if df.empty:
        return {"note": "Keine 'record'-Daten gefunden."}

    start_ts_utc = df["timestamp"].min()
    end_ts_utc = df["timestamp"].max()
    elapsed_s = (end_ts_utc - start_ts_utc).total_seconds()

    moving_mask = (df["speed_m_s"].fillna(0) > 0.5)
    moving_s = float(df.loc[moving_mask, "timestamp"].diff().dt.total_seconds().fillna(0).sum())

    total_dist_m = float(df["distance_m"].max(skipna=True) or 0.0)
    avg_speed_m_s = total_dist_m / elapsed_s if elapsed_s > 0 else 0.0
    max_speed_m_s = float(df["speed_m_s"].max() or 0.0)

    ascent_m = positive_gain(df["altitude_m"]) if "altitude_m" in df else 0.0

    hr_avg = float(df["heart_rate_bpm"].mean()) if df["heart_rate_bpm"].notna().any() else None
    hr_max = float(df["heart_rate_bpm"].max()) if df["heart_rate_bpm"].notna().any() else None
    cad_avg = float(df["cadence_rpm"].mean()) if df["cadence_rpm"].notna().any() else None
    cad_max = float(df["cadence_rpm"].max()) if df["cadence_rpm"].notna().any() else None
    pwr_avg = float(df["power_w"].mean()) if df["power_w"].notna().any() else None
    pwr_max = float(df["power_w"].max()) if df["power_w"].notna().any() else None
    temp_avg = float(df["temperature_c"].mean()) if df["temperature_c"].notna().any() else None

    # Fahrerarbeit
    rider_work_J = integrate_work_joules(df)
    rider_work_Wh = rider_work_J / 3600.0

    # Motorenergie aus Wall-Messung
    motor_energy_Wh = None
    if wall_energy_kWh and eff_wall2batt_pct:
        motor_energy_Wh = wall_energy_kWh * 1000.0 * (eff_wall2batt_pct/100.0)

    total_work_Wh = rider_work_Wh + (motor_energy_Wh or 0.0)
    total_work_J = total_work_Wh * 3600.0

    # Kalorien-Schätzung
    calories_mech = rider_work_J / 4184.0
    calories_food = None
    calories_range = None
    if muscle_eff_pct:
        calories_food = calories_mech / (muscle_eff_pct/100.0)
        calories_range = {
            "20%": round(calories_mech / 0.20, 1),
            "25%": round(calories_mech / 0.25, 1),
        }

    # Zeit in Berlin
    start_local = start_ts_utc.tz_convert(LOCAL_TZ)
    end_local = end_ts_utc.tz_convert(LOCAL_TZ)
    start_str = start_local.strftime("%Y-%m-%dT%H:%M:%S%z")
    end_str = end_local.strftime("%Y-%m-%dT%H:%M:%S%z")

    summary = {
        "start_time": start_str,
        "end_time": end_str,
        "timezone": LOCAL_TZ,
        "elapsed_time_s": round(elapsed_s, 1),
        "moving_time_s": round(moving_s, 1),
        "distance_m": round(total_dist_m, 1),
        "avg_speed_kmh": round(avg_speed_m_s * 3.6, 2),
        "max_speed_kmh": round(max_speed_m_s * 3.6, 2),
        "elevation_gain_m": round(ascent_m, 1),
        "avg_cadence_rpm": round(cad_avg, 1) if cad_avg is not None else None,
        "max_cadence_rpm": round(cad_max, 1) if cad_max is not None else None,
        "avg_power_w": round(pwr_avg, 1) if pwr_avg is not None else None,
        "max_power_w": round(pwr_max, 1) if pwr_max is not None else None,
        # Energetik
        "rider_work_Wh": round(rider_work_Wh, 2),
        "rider_work_J": round(rider_work_J, 1),
        "motor_energy_Wh": round(motor_energy_Wh, 2) if motor_energy_Wh else None,
        "total_work_Wh": round(total_work_Wh, 2),
        "total_work_J": round(total_work_J, 1),
        # Kalorien
        "calories_mechanical_kcal": round(calories_mech, 1),
        "calories_food_est_kcal": round(calories_food, 1) if calories_food else None,
        "calories_food_est_range_kcal": calories_range,
        # Eingaben
        "wall_energy_kWh_input": wall_energy_kWh,
        "wall2battery_eff_pct_input": eff_wall2batt_pct,
        "muscle_eff_pct_input": muscle_eff_pct,
    }

    return summary


# --- Export -------------------------------------------------------------------
def export_timeseries_csv(df: pd.DataFrame, out_prefix: Path) -> Path:
    out_csv = out_prefix.with_suffix(".csv")
    df_out = df.copy()
    df_out["timestamp_iso"] = df_out["timestamp"].dt.tz_convert(LOCAL_TZ).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    cols = [
        "timestamp_iso",
        "latitude_deg", "longitude_deg", "altitude_m", "speed_m_s",
        "distance_m", "heart_rate_bpm", "cadence_rpm", "power_w", "temperature_c"
    ]
    df_out[cols].to_csv(out_csv, index=False, sep=';', decimal=',')
    return out_csv


def export_summary_json(summary: Dict[str, Any], out_prefix: Path) -> Path:
    out_json = out_prefix.with_suffix(".json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return out_json


# --- GUI Inputs ---------------------------------------------------------------
def ask_user_inputs_gui() -> Optional[Dict[str, Any]]:
    if tk is None:
        return None
    root = tk.Tk(); root.withdraw(); root.update()
    try:
        file_path = filedialog.askopenfilename(title="FIT-Datei wählen",
                                               filetypes=[("FIT-Dateien", "*.fit"), ("Alle Dateien", "*.*")])
        if not file_path:
            return None
        wall_kWh = simpledialog.askfloat("Nachladeenergie", "Energie aus Steckdose (z.B. 0.5 kWh):", minvalue=0.01, maxvalue=5.0, initialvalue=0.5)
        eff_pct = simpledialog.askfloat("Wall→Battery Effizienz", "Effizienz in % (z. B. 82.5):", minvalue=10, maxvalue=100, initialvalue=82.5)
        muscle_eff = simpledialog.askfloat("Muskeleffizienz", "Muskeleffizienz in % (Default 24):", minvalue=5, maxvalue=40, initialvalue=24)
        return {"fit_file": file_path, "wall_energy_kWh": wall_kWh, "eff_pct": eff_pct, "muscle_eff": muscle_eff}
    finally:
        try:
            root.destroy()
        except Exception:
            pass


# --- Main ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Analyse einer FIT-Datei (Bosch eBike Flow)")
    ap.add_argument("fit_file", nargs="?", help="Pfad zur FIT-Datei")
    ap.add_argument("--wall-energy-kwh", type=float, default=0.5, help="Nachladeenergie aus der Steckdose (kWh)")
    ap.add_argument("--wall2battery-eff-pct", type=float, default=82.5, help="Effizienz Wall→Battery in %")
    ap.add_argument("--muscle-eff-pct", type=float, default=24.0, help="Muskeleffizienz in % (Default 24)")
    args = ap.parse_args()

    if args.fit_file:
        inputs = {"fit_file": args.fit_file,
                  "wall_energy_kWh": args.wall_energy_kwh,
                  "eff_pct": args.wall2battery_eff_pct,
                  "muscle_eff": args.muscle_eff_pct}
    else:
        inputs = ask_user_inputs_gui()
        if not inputs:
            print("Abgebrochen."); sys.exit(1)

    fit_path = Path(inputs["fit_file"]).expanduser().resolve()
    if not fit_path.exists():
        print(f"Datei nicht gefunden: {fit_path}"); sys.exit(2)

    out_prefix = fit_path.with_suffix("")
    out_prefix = out_prefix.parent / f"{fit_path.stem}_analysis"

    df = parse_fit_records(fit_path)
    agg = parse_sessions_and_laps(fit_path)
    summary = compute_metrics(df, agg,
                              wall_energy_kWh=inputs.get("wall_energy_kWh"),
                              eff_wall2batt_pct=inputs.get("eff_pct"),
                              muscle_eff_pct=inputs.get("muscle_eff"))

    out_csv = export_timeseries_csv(df, out_prefix)
    out_json = export_summary_json(summary, out_prefix)

    print(f"CSV: {out_csv}")
    print(f"JSON: {out_json}")
    if tk is not None:
        try:
            messagebox.showinfo("Fertig", f"CSV und JSON gespeichert:\n{out_csv}\n{out_json}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
