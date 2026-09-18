from __future__ import annotations

from local_ai_hub.dashboard import DASHBOARD_HTML


def test_dashboard_exposes_frontend_vision_review_input_flow() -> None:
    for marker in (
        'id="visionReviewModal"',
        'id="visionScreenshot"',
        'id="visionPrompt"',
        'id="visionCaptureState"',
        'id="visionCaptureError"',
        'Capture current tab',
        'function openFrontendVisionReviewModal(',
        'async function submitFrontendVisionReview(',
        'function captureFrontendVisionTab(',
        "'/api/vision/review'",
        "permission_denied",
    ):
        assert marker in DASHBOARD_HTML, f"Vision review contract marker missing: {marker}"


def test_trace_presents_vision_review_summary_before_expandable_evidence() -> None:
    for marker in (
        "function traceVisionReviewPayload(",
        "function renderVisionReviewPresentation(",
        "function traceVisionCaptureState(",
        'data-vision-review',
        'data-vision-evidence="${esc(key)}"',
        "evidence('screenshot'",
        "evidence('dom'",
        "evidence('accessibility'",
        "evidence('raw-output'",
        'data-repair-finding',
        'finding_id',
        'model provenance',
    ):
        assert marker in DASHBOARD_HTML, f"Vision trace marker missing: {marker}"

    summary = DASHBOARD_HTML.index("function renderVisionReviewPresentation(")
    technical = DASHBOARD_HTML.index('id="traceTechnicalDetails"')
    assert summary < technical, "Vision summary must render before technical trace details"


def test_vision_review_renderer_uses_existing_bounded_escaping() -> None:
    start = DASHBOARD_HTML.index("function renderVisionReviewPresentation(")
    end = DASHBOARD_HTML.index("function renderRepoIntelligencePresentation(", start)
    renderer = DASHBOARD_HTML[start:end]
    assert "traceFinalizeMarkup" in renderer
    assert "esc(" in renderer
    assert "tracePresentationValue" in renderer
