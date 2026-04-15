from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from .models import UserClusterLabel


@dataclass(frozen=True)
class ClusterSample:
    kpm: float
    app_score: float
    is_work_hour_score: float


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
    def __init__(self, retrain_interval_hours: int = 24, ema_alpha: float = 0.3) -> None:
        self.retrain_interval = timedelta(hours=retrain_interval_hours)
        self.ema_alpha = max(0.0, min(1.0, ema_alpha))
        self.last_trained_at: datetime | None = None
        self.centers: list[tuple[float, float, float]] = []
        self.cluster_labels: dict[int, UserClusterLabel] = {}

    def ensure_model(self, history_rows: list[dict], now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        if self.last_trained_at is not None and now - self.last_trained_at < self.retrain_interval:
            return

        samples = self._build_samples(history_rows=history_rows)
        new_centers, new_labels = self._fit(samples)
        self.centers, self.cluster_labels = self._merge_with_ema(new_centers, new_labels)
        self.last_trained_at = now

    def predict(
        self,
        kpm_value: int,
        app_name: str | None,
        is_work_hour: bool = False,
    ) -> tuple[UserClusterLabel, float]:
        if not self.centers:
            return "offline_rest", 1.0

        feature = (float(kpm_value), _app_score(app_name), 1.0 if is_work_hour else 0.0)
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
            is_work_hour = bool(row.get("is_work_hour", False))
            samples.append(
                ClusterSample(
                    kpm=kpm_value,
                    app_score=_app_score(app_name),
                    is_work_hour_score=1.0 if is_work_hour else 0.0,
                )
            )
        return samples

    def _fit(
        self,
        samples: list[ClusterSample],
    ) -> tuple[list[tuple[float, float, float]], dict[int, UserClusterLabel]]:
        points = [(sample.kpm, sample.app_score, sample.is_work_hour_score) for sample in samples]
        if len(points) < 3:
            return (
                [(0.0, 0.0, 0.0), (30.0, 0.5, 1.0), (100.0, 0.9, 1.0)],
                {0: "offline_rest", 1: "low_energy", 2: "deep_work"},
            )

        sorted_points = sorted(points, key=lambda item: item[0])
        quantile_indexes = [len(sorted_points) // 6, len(sorted_points) // 2, (len(sorted_points) * 5) // 6]
        centers = [sorted_points[index] for index in quantile_indexes]

        for _ in range(25):
            assignments: list[list[tuple[float, float, float]]] = [[], [], []]
            for point in points:
                nearest = min(range(3), key=lambda idx: self._distance(point, centers[idx]))
                assignments[nearest].append(point)

            updated_centers: list[tuple[float, float, float]] = []
            for idx, bucket in enumerate(assignments):
                if not bucket:
                    updated_centers.append(centers[idx])
                    continue
                avg_kpm = sum(p[0] for p in bucket) / len(bucket)
                avg_app_score = sum(p[1] for p in bucket) / len(bucket)
                avg_work_score = sum(p[2] for p in bucket) / len(bucket)
                updated_centers.append((avg_kpm, avg_app_score, avg_work_score))

            if self._centers_stable(old=centers, new=updated_centers):
                centers = updated_centers
                break
            centers = updated_centers

        ordered = sorted(enumerate(centers), key=lambda item: item[1][0])
        mapped_labels = ["offline_rest", "low_energy", "deep_work"]
        cluster_labels = {
            original_index: mapped_labels[rank]
            for rank, (original_index, _) in enumerate(ordered)
        }
        return centers, cluster_labels

    def _merge_with_ema(
        self,
        new_centers: list[tuple[float, float, float]],
        new_labels: dict[int, UserClusterLabel],
    ) -> tuple[list[tuple[float, float, float]], dict[int, UserClusterLabel]]:
        canonical_labels: list[UserClusterLabel] = ["offline_rest", "low_energy", "deep_work"]
        new_by_label = self._build_label_center_map(new_centers, new_labels)
        old_by_label = self._build_label_center_map(self.centers, self.cluster_labels)

        merged_centers: list[tuple[float, float, float]] = []
        for label in canonical_labels:
            new_center = new_by_label.get(label)
            old_center = old_by_label.get(label)
            if new_center is None and old_center is None:
                merged_centers.append((0.0, 0.0, 0.0))
                continue
            if old_center is None:
                merged_centers.append(new_center)  # type: ignore[arg-type]
                continue
            if new_center is None:
                merged_centers.append(old_center)
                continue
            merged_centers.append(
                (
                    (self.ema_alpha * new_center[0]) + ((1.0 - self.ema_alpha) * old_center[0]),
                    (self.ema_alpha * new_center[1]) + ((1.0 - self.ema_alpha) * old_center[1]),
                    (self.ema_alpha * new_center[2]) + ((1.0 - self.ema_alpha) * old_center[2]),
                )
            )

        merged_labels = {idx: label for idx, label in enumerate(canonical_labels)}
        return merged_centers, merged_labels

    def _build_label_center_map(
        self,
        centers: list[tuple[float, float, float]],
        labels: dict[int, UserClusterLabel],
    ) -> dict[UserClusterLabel, tuple[float, float, float]]:
        mapping: dict[UserClusterLabel, tuple[float, float, float]] = {}
        for idx, label in labels.items():
            if 0 <= idx < len(centers):
                mapping[label] = centers[idx]
        return mapping

    def _centers_stable(
        self,
        old: list[tuple[float, float, float]],
        new: list[tuple[float, float, float]],
    ) -> bool:
        for old_center, new_center in zip(old, new):
            if self._distance(old_center, new_center) > 0.05:
                return False
        return True

    def _distance(self, lhs: tuple[float, float, float], rhs: tuple[float, float, float]) -> float:
        # Weighted distance: typing cadence strongest, app semantics second, work-hour context third.
        return math.sqrt(
            ((lhs[0] - rhs[0]) ** 2)
            + ((lhs[1] - rhs[1]) ** 2) * 36.0
            + ((lhs[2] - rhs[2]) ** 2) * 25.0
        )
