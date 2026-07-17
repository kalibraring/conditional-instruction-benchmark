from __future__ import annotations

import hashlib
import secrets
from dataclasses import asdict, dataclass, field
from typing import Any

from .trials import Arm, TrialSpec


SCHEMA_VERSION = "cib/1"
EVIDENCE_SCHEMA_VERSION = "cib-evidence/1"


@dataclass(frozen=True)
class ManifestRow:
    run_id: str
    trial_id: str
    block_id: str
    random_order: int
    arm: Arm
    condition_true: bool
    case_id: str
    case_variant: int
    placement: str
    model: str
    reasoning_effort: str
    target_adapter: str
    nonce: str
    nonce_hash: str
    protocol_version: str = SCHEMA_VERSION
    profile: str = "scientific"
    is_primary: bool = True

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        trial_id: str,
        block_id: str,
        random_order: int,
        arm: Arm,
        condition_true: bool,
        case_id: str,
        case_variant: int,
        placement: str,
        model: str,
        reasoning_effort: str,
        target_adapter: str,
        nonce: str | None = None,
        profile: str = "scientific",
        is_primary: bool = True,
    ) -> "ManifestRow":
        actual_nonce = nonce or secrets.token_hex(16)
        return cls(
            run_id=run_id,
            trial_id=trial_id,
            block_id=block_id,
            random_order=random_order,
            arm=arm,
            condition_true=condition_true,
            case_id=case_id,
            case_variant=case_variant,
            placement=placement,
            model=model,
            reasoning_effort=reasoning_effort,
            target_adapter=target_adapter,
            nonce=actual_nonce,
            nonce_hash=hashlib.sha256(actual_nonce.encode()).hexdigest(),
            profile=profile,
            is_primary=is_primary,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ManifestRow":
        data = dict(value)
        nonce = str(data["nonce"])
        calculated_hash = hashlib.sha256(nonce.encode()).hexdigest()
        supplied_hash = data.get("nonce_hash")
        if supplied_hash not in (None, calculated_hash):
            raise ValueError("Manifest nonce_hash does not match nonce")
        data["nonce_hash"] = calculated_hash
        data.setdefault("protocol_version", SCHEMA_VERSION)
        data.setdefault("profile", "scientific")
        data.setdefault("is_primary", True)
        return cls(**data)

    def to_private_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_public_dict(self) -> dict[str, Any]:
        value = self.to_private_dict()
        value.pop("nonce")
        return value

    def to_spec(self) -> TrialSpec:
        return TrialSpec(
            trial_id=self.trial_id,
            arm=self.arm,
            condition_true=self.condition_true,
            placement=self.placement,  # type: ignore[arg-type]
            case_id=self.case_id,
            case_variant=self.case_variant,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )


@dataclass(frozen=True)
class MaterializedTrial:
    manifest: ManifestRow
    working_dir: str
    home: str
    codex_home: str
    fixture_hash: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MaterializedTrial":
        manifest_fields = ManifestRow.__dataclass_fields__
        manifest = ManifestRow.from_dict(
            {key: value[key] for key in manifest_fields if key in value}
        )
        return cls(
            manifest=manifest,
            working_dir=str(value["working_dir"]),
            home=str(value["home"]),
            codex_home=str(value["codex_home"]),
            fixture_hash=str(value["fixture_hash"]),
        )

    def to_private_dict(self) -> dict[str, Any]:
        return {
            **self.manifest.to_private_dict(),
            "working_dir": self.working_dir,
            "home": self.home,
            "codex_home": self.codex_home,
            "fixture_hash": self.fixture_hash,
        }

    def to_public_dict(self) -> dict[str, Any]:
        return {
            **self.manifest.to_public_dict(),
            "fixture_hash": self.fixture_hash,
        }


@dataclass
class EvidenceEnvelope:
    manifest: dict[str, Any]
    execution: dict[str, Any]
    response: dict[str, Any]
    evidence: dict[str, Any]
    observation: dict[str, Any]
    outcome: dict[str, Any]
    provenance: dict[str, Any]
    schema_version: str = field(default=EVIDENCE_SCHEMA_VERSION, init=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
