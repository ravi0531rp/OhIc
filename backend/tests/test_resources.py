from app.core.resources import plan_resources, resource_snapshot


def test_resource_plan_reduces_tiles_and_parallelism_under_pressure(monkeypatch):
    monkeypatch.setattr("app.core.resources._memory", lambda: (16_384, 1_000))
    monkeypatch.setattr("app.core.resources.os.getloadavg", lambda: (1.0, 1.0, 1.0))

    snapshot = resource_snapshot()
    plan = plan_resources("auto", 3840 * 2160)

    assert snapshot.memory_pressure == "critical"
    assert plan.tile_size == 128
    assert plan.temporal_window == 5
    assert plan.max_parallel_jobs == 1


def test_performance_policy_expands_safe_temporal_window(monkeypatch):
    monkeypatch.setattr("app.core.resources._memory", lambda: (32_768, 20_000))
    monkeypatch.setattr("app.core.resources.os.getloadavg", lambda: (1.0, 1.0, 1.0))

    automatic = plan_resources("auto", 1280 * 720)
    performance = plan_resources("performance", 1280 * 720)

    assert performance.tile_size > automatic.tile_size
    assert performance.temporal_window > automatic.temporal_window


def test_user_memory_ceiling_caps_automatic_plan(monkeypatch):
    monkeypatch.setattr("app.core.resources._memory", lambda: (32_768, 20_000))
    monkeypatch.setattr("app.core.resources.os.getloadavg", lambda: (1.0, 1.0, 1.0))

    plan = plan_resources("auto", 1280 * 720, memory_limit_mb=2048)

    assert plan.tile_size == 192
    assert "2048 MB" in plan.rationale
