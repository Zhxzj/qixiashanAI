"""天气 + 红叶指数：Open-Meteo（免 key）为主，本地缓存 + 手动兜底。"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

import httpx

LAT, LNG = 32.1538, 118.9587  # 栖霞山
API = "https://api.open-meteo.com/v1/forecast"
TTL = 900  # 缓存 15 分钟

def park_date():
    return datetime.now(timezone(timedelta(hours=8))).date()

WMO = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "小雨", 55: "中雨", 61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨", 71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷暴",
}


def _date_curve(d: date) -> float:
    """红叶日期曲线：10-05 起色 → 11-15 最盛 → 之后缓降。"""
    pts = [
        (date(d.year, 10, 5), 0.10),
        (date(d.year, 10, 15), 0.35),
        (date(d.year, 10, 25), 0.60),
        (date(d.year, 11, 1), 0.80),
        (date(d.year, 11, 15), 0.95),
        (date(d.year, 11, 30), 0.75),
        (date(d.year, 12, 15), 0.30),
    ]
    if d <= pts[0][0]:
        return pts[0][1]
    if d >= pts[-1][0]:
        return pts[-1][1]
    for (d1, v1), (d2, v2) in zip(pts, pts[1:]):
        if d1 <= d <= d2:
            r = (d - d1).days / max(1, (d2 - d1).days)
            return v1 + (v2 - v1) * r
    return 0.30


def _red_leaf_text(score: int) -> str:
    if score < 25:
        return "还没红"
    if score < 45:
        return "刚见红"
    if score < 65:
        return "红了小半"
    if score < 85:
        return "红了七成，正当时"
    return "正红"


class ConditionsService:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self._cache: dict | None = None
        self._cache_ts = 0.0
        self.client = None
        self._lock = asyncio.Lock()
        try:
            self._manual = json.loads(
                (self.data_dir / "manual_conditions.json").read_text(encoding="utf-8")
            )
        except Exception:
            self._manual = {}


    async def get(self, days=1, force=False):
        days=max(1,min(3,int(days)))
        async with self._lock:
            now=time.time()
            today=park_date().isoformat()
            ttl=60 if (self._cache or {}).get("source")=="fallback" else TTL
            if not force and self._cache and self._cache.get("requested_date")==today and now-self._cache_ts<ttl and self._cache.get("requested_days",self._cache.get("days",1))>=days:
                return self._cache
            try:
                data=await self._fetch(days)
            except Exception as e:
                data=self._fallback(type(e).__name__)
            data["requested_days"]=days
            data["requested_date"]=today
            data["data_date"]=today if data["source"]=="open-meteo" else self._manual.get("data_date")
            data["kind"]="forecast" if data["source"]=="open-meteo" else "fallback_not_live"
            data["red_leaf"]["kind"]="manual" if self._manual.get("red_leaf_override") is not None else "estimated"
            self._cache,self._cache_ts=data,now
            return data

    async def _fetch(self, days: int) -> dict:
        params = {
            "latitude": LAT,
            "longitude": LNG,
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunset",
            "timezone": "Asia/Shanghai",
            "forecast_days": max(1, min(3, days)),
            "past_days": 7,
        }
        resp = await self.client.get(API, params=params)
        resp.raise_for_status()
        raw = resp.json()
        cur = raw.get("current", {})
        daily = raw.get("daily", {})
        times = daily.get("time", [])
        mins = daily.get("temperature_2m_min", [])
        maxs = daily.get("temperature_2m_max", [])
        rains = daily.get("precipitation_probability_max", [])
        sunsets = daily.get("sunset", [])
        n_past = 7
        forecast = []
        for i in range(n_past, len(times)):
            forecast.append(
                {
                    "date": times[i],
                    "min": mins[i] if i < len(mins) else None,
                    "max": maxs[i] if i < len(maxs) else None,
                    "rain_prob": rains[i] if i < len(rains) else None,
                }
            )
        today = forecast[0] if forecast else {}
        w = {
            "now": {
                "temp_c": cur.get("temperature_2m"),
                "text": WMO.get(cur.get("weather_code"), "多云"),
                "wind": f"{cur.get('wind_speed_10m')} km/h",
            },
            "today": {
                "min": today.get("min"),
                "max": today.get("max"),
                "rain_prob": today.get("rain_prob"),
                "sunset": sunsets[n_past] if len(sunsets) > n_past else None,
            },
            "forecast": forecast,
        }
        red = self._compute_red_leaf(mins[:n_past])
        return {
            "days": days,
            "source": "open-meteo",
            "weather": w,
            "red_leaf": red,
            "advice": self._advice(w, red),
            "updated_ts": int(time.time()),
        }

    def _fallback(self, err: str) -> dict:
        fb = self._manual.get("fallback_weather", {}) or {}
        w = {
            "now": {"temp_c": fb.get("temp_c"), "text": fb.get("text", "多云"), "wind": fb.get("wind", "微风")},
            "today": {
                "min": fb.get("min"),
                "max": fb.get("max"),
                "rain_prob": fb.get("rain_prob"),
                "sunset": fb.get("sunset", "17:22"),
            },
            "forecast": [],
        }
        red = self._compute_red_leaf(None)
        return {
            "days": 1,
            "source": "fallback",
            "weather": w,
            "red_leaf": red,
            "advice": ["天气服务暂时不可用，先用本地记录顶着"],
            "updated_ts": int(time.time()),
        }

    def _compute_red_leaf(self, past_mins: list | None) -> dict:
        override = self._manual.get("red_leaf_override")
        if override is not None:
            score = int(override)
            return {
                "score": score,
                "text": _red_leaf_text(score),
                "trend": self._manual.get("note") or "人工记录，采集日期未核验",
            }
        curve = _date_curve(park_date())
        if past_mins:
            cold = sum(max(0.0, 12.0 - m) for m in past_mins if m is not None)
        else:
            cold = 25.0  # 离线粗估
        cold_norm = min(1.0, cold / 60.0)
        score = int(max(0, min(100, round(60 * curve + 40 * cold_norm))))
        return {"score": score, "text": _red_leaf_text(score), "trend": ""}

    @staticmethod
    def _advice(w: dict, red: dict) -> list:
        out = []
        today = w.get("today", {})
        rain = today.get("rain_prob")
        if rain is not None and rain >= 50:
            out.append(f"今天下雨概率 {rain}%，带上伞，石阶路滑")
        tmax = today.get("max")
        if tmax is not None and tmax >= 28:
            out.append("日头有点烈，走林荫多的路")
        if red.get("score", 0) >= 65:
            out.append("红叶正当时，霜红苑和枫林湖方向最密")
        if today.get("sunset"):
            out.append(f"落日约 {today['sunset']}，山顶看晚霞要提前半小时到")
        return out

