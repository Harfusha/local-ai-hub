"""Offline end-to-end contract for the frontend vision review flow.

This is intentionally a fixture/state test, not a real browser or Ollama test.
"""

from __future__ import annotations

from pathlib import Path
import re
from tempfile import TemporaryDirectory

from local_ai_hub.frontend_review import build_coder_context, build_model_context


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "frontend_review"
VIEWPORT_HEIGHT = 844


def _element(element_id: str, *, ancestor_ids: list[str] | None = None) -> dict:
    return {
        "element_id": element_id,
        "tag": "div",
        "text": element_id,
        "ancestor_ids": ancestor_ids or ["root"],
    }


def _dom_bundle(html: str) -> dict:
    return {
        "redaction": "none",
        "html": html,
        "elements": [
            _element("root", ancestor_ids=[]),
            _element("icon-button"),
            _element("contrast-copy"),
            _element("fake-auth-state"),
            _element("mobile-cta"),
        ],
    }


def _mock_vision_response() -> dict:
    return {
        "summary": "The fixture has four intentional frontend issues.",
        "findings": [
            {
                "finding_id": "cta-below-fold",
                "problem": "The mobile CTA is below the initial viewport.",
                "observed": "The CTA uses a 120vh top margin.",
                "hypothesized": "The CTA is unavailable at the mobile entry point.",
                "uncertainty": [],
                "element_ids": ["mobile-cta"],
                "evidence": ["screenshot", "computed_styles"],
                "fix_hint": "Use normal flow spacing on mobile.",
            },
            {
                "finding_id": "muted-contrast",
                "problem": "Body copy has insufficient contrast.",
                "observed": "The muted copy is #a0a0a0 on white.",
                "hypothesized": "Normal-sized text will fail WCAG contrast.",
                "uncertainty": [],
                "element_ids": ["contrast-copy"],
                "evidence": ["screenshot", "computed_styles"],
                "fix_hint": "Use a darker text color.",
            },
            {
                "finding_id": "icon-name",
                "problem": "The icon button has no accessible name.",
                "observed": "The button has no aria-label or visible label.",
                "hypothesized": "Screen readers announce an unnamed control.",
                "uncertainty": [],
                "element_ids": ["icon-button"],
                "evidence": ["accessibility"],
                "fix_hint": "Add an aria-label.",
            },
            {
                "finding_id": "console-error",
                "problem": "The page emits a console error.",
                "observed": "The fixture emits one deliberate console.error.",
                "hypothesized": "A runtime failure can hide user-facing regressions.",
                "uncertainty": [],
                "element_ids": ["root"],
                "evidence": ["runtime"],
                "fix_hint": "Remove the deliberate runtime error.",
            },
        ],
        "unknowns": [],
        "recommended_checks": ["browser_recheck"],
    }


def _active_findings(html: str, css: str) -> set[str]:
    active: set[str] = set()
    if re.search(r"margin-top:\s*120vh", css):
        active.add("cta-below-fold")
    if re.search(r"\.muted\s*\{[^}]*color:\s*#a0a0a0", css, re.S | re.I):
        active.add("muted-contrast")
    if not re.search(r'<button[^>]+data-testid="icon-button"[^>]+aria-label=', html, re.I):
        active.add("icon-name")
    if "console.error(" in html:
        active.add("console-error")
    return active


def test_frontend_review_fixture_repairs_and_clears_findings() -> None:
    html_path = FIXTURE_DIR / "index.html"
    css_path = FIXTURE_DIR / "app.css"
    broken_html = html_path.read_text(encoding="utf-8")
    broken_css = css_path.read_text(encoding="utf-8")

    assert _active_findings(broken_html, broken_css) == {
        "cta-below-fold",
        "muted-contrast",
        "icon-name",
        "console-error",
    }
    assert 'data-authenticated="true"' in broken_html
    assert "password" not in broken_html.lower()

    dom = _dom_bundle(broken_html)
    model_context = build_model_context(
        prompt="Review this mobile frontend and report actionable defects.",
        screenshot_data_url="data:image/png;base64,ZmFrZS1zY3JlZW5zaG90",
        dom=dom,
        accessibility={
            "icon-button": {"role": "button", "accessible_name": ""},
        },
        computed_styles={
            "mobile-cta": {"margin_top": "120vh", "viewport_height": VIEWPORT_HEIGHT},
            "contrast-copy": {"color": "#a0a0a0", "background": "#ffffff"},
        },
        viewport={"width": 390, "height": VIEWPORT_HEIGHT, "device": "mobile"},
        runtime={"console_errors": ["frontend-review-fixture: deliberate console error"]},
    )
    review = _mock_vision_response()
    repo_context = {
        "files": [
            {"path": "tests/fixtures/frontend_review/index.html", "content": broken_html},
            {"path": "tests/fixtures/frontend_review/app.css", "content": broken_css},
        ]
    }
    coder = build_coder_context(
        review,
        {
            "prompt": model_context.prompt,
            "dom": model_context.dom,
            "accessibility": model_context.accessibility,
            "computed_styles": model_context.computed_styles,
            "viewport": model_context.viewport,
            "runtime": model_context.runtime,
        },
        repo_context,
    )

    assert coder["success"] is True
    assert {item["element_id"] for item in coder["dom"]["elements"]} == {
        "root",
        "mobile-cta",
        "contrast-copy",
        "icon-button",
    }
    assert [item["path"] for item in coder["repo"]["files"]] == [
        "tests/fixtures/frontend_review/index.html",
        "tests/fixtures/frontend_review/app.css",
    ]
    assert len(coder["dom"]["html"]) <= len(broken_html)
    assert "credentials" not in coder["dom"]["html"].lower()

    # Repair and recheck a temporary copy. The committed fixture remains the broken target.
    with TemporaryDirectory() as temporary:
        repaired_dir = Path(temporary)
        repaired_html = broken_html.replace(
            '<button class="icon-button" data-testid="icon-button" type="button">',
            '<button class="icon-button" data-testid="icon-button" aria-label="Open navigation" type="button">',
        ).replace(
            '    console.error("frontend-review-fixture: deliberate console error");\n',
            "",
        )
        repaired_css = broken_css.replace("color: #a0a0a0;", "color: #3d4658;").replace(
            "margin-top: 120vh;", "margin-top: 1rem;"
        )
        (repaired_dir / "index.html").write_text(repaired_html, encoding="utf-8")
        (repaired_dir / "app.css").write_text(repaired_css, encoding="utf-8")

        rechecked_html = (repaired_dir / "index.html").read_text(encoding="utf-8")
        rechecked_css = (repaired_dir / "app.css").read_text(encoding="utf-8")
        assert _active_findings(rechecked_html, rechecked_css) == set()
        assert "aria-label=\"Open navigation\"" in rechecked_html
        assert "#3d4658" in rechecked_css
        assert "margin-top: 1rem" in rechecked_css
        assert "console.error(" not in rechecked_html
