"""Generate a v3-format sample project repo.

A reusable seed for verification: drafts a small subscription-billing
project tier-by-tier through the real ``siege`` CLI write path, then
commits. Used by two callers:

- ``scripts/make_sample_project.py`` — the CLI shim, for hand-runs.
- ``backend.projects.import_service.create_sample_project`` — the
  dashboard's "Use sample project" button, which calls ``build``
  in-process so the deployed server can materialize a substrate
  without needing siege on the subprocess sys.path.

The project: five features, four responsibilities, four top-level
components (a foundation, two domains, one presentational) wired with
dependency + domain-parent edges, and a comparch decomposition for the
two domain components. Every comp (including foundation) owns at
least one responsibility so the resp → comp decomposition projection
has something to emit per top-level node. The foundation and
presentational components are left without a comparch on purpose —
they project as ``status: "absent"`` so the graph shows a realistic
mix of lifecycle states.
"""

# The embedded artifact bodies are XML elements kept one-per-line for
# readability; long lines are inherent to that.
# ruff: noqa: E501

from __future__ import annotations

import contextlib
import io
import json
import subprocess
from pathlib import Path

from siege.cli import main as cli_main


def _run_cli(argv: list[str]) -> None:
    """Run a siege CLI command, swallowing its JSON stdout."""
    with contextlib.redirect_stdout(io.StringIO()):
        rc = cli_main(argv)
    if rc != 0:
        raise RuntimeError(f"siege {argv[0]} failed (rc={rc}); argv={argv}")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _write_body(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _draft(repo: Path, tier: str, comp_id: str, body_rel: str) -> None:
    _run_cli(
        [
            "write-draft",
            "--repo",
            str(repo),
            "--tier",
            tier,
            "--comp-id",
            comp_id,
            "--body-path",
            body_rel,
        ]
    )


def _ledger_ids(repo: Path, tier: str, comp_id: str, key: str) -> dict[str, str]:
    """Map a ledger's carry-forward key (name / alias) -> minted node id."""
    data = json.loads((repo / "ids" / tier / f"{comp_id}.json").read_text())
    return {n[key]: n["id"] for n in data["nodes"]}


# ---- bodies -------------------------------------------------------------

_FEATURE_BODY = """\
<introduction>
A subscription billing platform with a customer portal and an operator
console.
</introduction>
<features>
  <feature><name>User Login</name><intent>Customers authenticate with email and password to reach their account.</intent></feature>
  <feature><name>Subscription Management</name><intent>Customers view their plan and switch between tiers.</intent></feature>
  <feature><name>Payment Collection</name><intent>The platform charges a customer's card each billing cycle.</intent></feature>
  <feature><name>Admin Audit Log</name><intent>Operators review a log of account-affecting actions.</intent><implicit/></feature>
  <feature><name>Durable Persistence</name><intent>System state survives restarts and disk-level recovery scenarios.</intent><implicit/></feature>
</features>
"""


def _sysarch_body(resp: dict[str, str]) -> str:
    """Build the sysarch body with per-component <responsibilities>
    blocks. The resp_* ids come from the requirements ledger so the
    v3 graph projection emits resp → comp decomposition edges that
    actually resolve."""
    return f"""\
## project_techspec

Python 3.11 on FastAPI, PostgreSQL via SQLAlchemy. Opaque server-side
session tokens; bcrypt credential hashing.

<components>
  <component alias="foundation"><name>Foundation</name><foundation/>
    <responsibilities>
      <resp id="{resp["Durable Storage Substrate"]}"/>
    </responsibilities>
  </component>
  <component alias="auth"><name>Auth Service</name>
    <responsibilities>
      <resp id="{resp["Authentication"]}"/>
    </responsibilities>
  </component>
  <component alias="billing"><name>Billing Service</name>
    <responsibilities>
      <resp id="{resp["Billing Lifecycle"]}"/>
      <resp id="{resp["Audit Trail"]}"/>
    </responsibilities>
  </component>
  <component alias="ui_billing"><name>Billing Console</name>
    <responsibilities>
      <resp id="{resp["Billing Lifecycle"]}"/>
    </responsibilities>
  </component>
</components>
<dependencies>
  <dep from="auth" to="foundation"/>
  <dep from="billing" to="auth"/>
  <dep from="billing" to="foundation"/>
</dependencies>
<domain-parent>
  <parent from="ui_billing" to="billing"/>
</domain-parent>
"""


_COMPARCH_BODIES = {
    "auth": """\
## comparch:techspec

Auth runs on the shared Postgres instance; sessions are server-side rows.

## comparch:pubapi

Exposes credential verification and session lookup.

<subcomponents>
  <subcomponent alias="credential_store"><name>CredentialStore</name><foundation/></subcomponent>
  <subcomponent alias="session_store"><name>SessionStore</name></subcomponent>
</subcomponents>
""",
    "billing": """\
## comparch:techspec

Billing reconciles against the payment processor on each billing cycle.

## comparch:pubapi

Exposes plan-change and cycle-charge operations.

<subcomponents>
  <subcomponent alias="plan_store"><name>PlanStore</name></subcomponent>
  <subcomponent alias="charger"><name>PaymentCharger</name></subcomponent>
</subcomponents>
""",
}


def _requirements_body(feat: dict[str, str]) -> str:
    return f"""\
<requirements>
  <responsibility><name>Authentication</name><feats><feat id="{feat["User Login"]}"/></feats></responsibility>
  <responsibility><name>Billing Lifecycle</name><feats><feat id="{feat["Subscription Management"]}"/><feat id="{feat["Payment Collection"]}"/></feats></responsibility>
  <responsibility><name>Audit Trail</name><feats><feat id="{feat["Admin Audit Log"]}"/></feats></responsibility>
  <responsibility><name>Durable Storage Substrate</name><feats><feat id="{feat["Durable Persistence"]}"/></feats></responsibility>
</requirements>
"""


def build(dest: Path) -> None:
    """Materialize the sample v3 project repo at ``dest``.

    Raises ``ValueError`` if ``dest`` already exists. Library-friendly:
    no ``print``, no ``SystemExit`` — the CLI shim handles user output.
    """
    if dest.exists():
        raise ValueError(f"destination already exists: {dest}")
    dest.mkdir(parents=True)
    _git(dest, "init", "-q")
    _git(dest, "config", "user.email", "sample@siege.local")
    _git(dest, "config", "user.name", "Siege Sample")
    # A generated fixture repo — no signing identity, and signing it
    # would serve no purpose.
    _git(dest, "config", "commit.gpgsign", "false")

    # feature_expansion — mints the feat_* identity ledger.
    _write_body(dest, "feature_expansion/proj/body.md", _FEATURE_BODY)
    _draft(dest, "feature_expansion", "proj", "feature_expansion/proj/body.md")
    feat = _ledger_ids(dest, "feature_expansion", "proj", "name")

    # requirements — its <feat> refs must be the minted feat ids.
    _write_body(dest, "requirements/proj/body.md", _requirements_body(feat))
    _draft(dest, "requirements", "proj", "requirements/proj/body.md")
    resp = _ledger_ids(dest, "requirements", "proj", "name")

    # sysarch — mints the comp_* ledger, declares the edges. The
    # per-component <responsibilities> blocks reference resp_* ids
    # from the ledger so the v3 graph projection emits resp → comp
    # decomposition edges.
    _write_body(dest, "sysarch/proj/body.md", _sysarch_body(resp))
    _draft(dest, "sysarch", "proj", "sysarch/proj/body.md")
    comp = _ledger_ids(dest, "sysarch", "proj", "alias")

    # comparch — only the two domain components get decomposed.
    for alias, body in _COMPARCH_BODIES.items():
        comp_id = comp[alias]
        rel = f"comparch/{comp_id}/body.md"
        _write_body(dest, rel, body)
        _draft(dest, "comparch", comp_id, rel)

    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "sample v3 project")
