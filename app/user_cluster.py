from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from .models import UserClusterLabel


@dataclass(frozen=True)
class ClusterSample:
    kpm: float
    app_score: float


def _normalize_app_name(app_name: str | None) -> str:
    return (app_name or "offline").strip().lower()


def _app_score(app_name: str | None) -> float:
    name = _normalize_app_name(app_name)
    if "code" in name or "cursor" in name or "pycharm" in name or "intellij" in name:
        return 1.0
    if "word" in name:
        return 0.8
    if "zoom" in name:
        return 0.4
    if "wechat" in name:
        return 0.3
    if "safari" in name or "chrome" in name or "firefox" in name:
        return 0.6
    return 0.0


class UserClusterEngine:
    def __init__(self, retrain_interval_hours: int = 24) -> None:
        self.retrain_interval = timedelta(hours=retrain_interval_hours)
        self.last_trained_at: datetime | None = None
        self.centers: list[tuple[float, float]] = []
        self.cluster_labels: dict[int, UserClusterLabel] = {}

    def ensure_model(self, history_rows: list[dict], now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        if self.last_trained_at is not None and now - self.last_trained_at < self.retrain_interval:
            return

        samples = self._build_samples(history_rows=history_rows)
        self._fit(samples)
        self.last_trained_at = now

    def predict(self, kpm_value: int, app_name: str | None) -> tuple[UserClusterLabel, float]:
        if not self.centers:
            return "offline_rest", 1.0

        feature = (float(kpm_value), _app_score(app_name))
        best_idx = 0
        best_distance = float("inf")
        for idx, center in enumerate(self.centers):
            distance = self._distance(feature, center)
            if distance < best_distance:
                best_idx = idx
                best_distance = distance

        label = self.cluster_labels.get(best_idx, "low_energy")
        confidence = max(0.35, min(1.0, 1.0 / (1.0 + best_distance)))
        return label, round(confidence, 3)

    def _build_samples(self, history_rows: list[dict]) -> list[ClusterSample]:
        samples: list[ClusterSample] = []
        for row in history_rows:
            kpm_value = float(row.get("kpm_value", 0))
            app_name = row.get("app_name")
            samples.append(ClusterSample(kpm=kpm_value, app_score=_app_score(app_name)))
        return samples

    def _fit(self, samples: list[ClusterSample]) -> None:
        points = [(sample.kpm, sample.app_score) for sample in samples]
        if len(points) < 3:
            self.centers = [(0.0, 0.0), (30.0, 0.5), (100.0, 0.9)]
            self.cluster_labels = {0: "offline_rest", 1: "low_energy", 2: "deep_work"}
            return

        sorted_points = sorted(points, key=lambda item: item[0])
        quantile_indexes = [len(sorted_points) // 6, len(sorted_points) // 2, (len(sorted_points) * 5) // 6]
        centers = [sorted_points[index] for index in quantile_indexes]

        for _ in range(25):
            assignments: list[list[tuple[float, float]]] = [[], [], []]
            for point in points:
                nearest = min(range(3), key=lambda idx: self._distance(point, centers[idx]))
                assignments[nearest].append(point)

            updated_centers: list[tuple[float, float]] = []
            for idx, bucket in enumerate(assignments):
                if not bucket:
                    updated_centers.append(centers[idx])
                    continue
                avg_kpm = sum(p[0] for p in bucket) / len(bucket)
                avg_app_score = sum(p[1] for p in bucket) / len(bucket)
                updated_centers.append((avg_kpm, avg_app_score))

            if self._centers_stable(old=centers, new=updated_centers):
                centers = updated_centers
                break
            centers = updated_centers

        ordered = sorted(enumerate(centers), key=lambda item: item[1][0])
        mapped_labels = ["offline_rest", "low_energy", "deep_work"]
        self.cluster_labels = {
            original_index: mapped_labels[rank]
            for rank, (original_index, _) in enumerate(ordered)
        }
        self.centers = centers

    def _centers_stable(
        self,
        old: list[tuple[float, float]],
        new: list[tuple[float, float]],
    ) -> bool:
        for old_center, new_center in zip(old, new):
            if self._distance(old_center, new_center) > 0.05:
                return False
        return True

    def _distance(self, lhs: tuple[float, float], rhs: tuple[float, float]) -> float:
        # Weighted distance: typing cadence is stronger than app category.
        return math.sqrt(((lhs[0] - rhs[0]) ** 2) + ((lhs[1] - rhs[1]) ** 2) * 36.0)
