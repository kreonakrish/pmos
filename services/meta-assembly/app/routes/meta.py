"""Meta-assembly route handlers — detect-gap, generate-spec, register."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, HTTPException

from app.models.meta import (
    DetectGapRequest,
    DetectGapResponse,
    GenerateSpecRequest,
    GenerateSpecResponse,
    RegisterRequest,
    RegisterResponse,
    ValidationResult,
)
from app.services.gap_detector import GapDetectorService
from app.services.spec_generator import SpecGeneratorService
from app.services.spec_validator import SpecValidatorService
from app.services.sandbox_runner import SandboxRunner
from app.services.capability_registrar import CapabilityRegistrar
from app.adapters.mysql_adapter import MySQLAdapter
from app.adapters.neo4j_adapter import Neo4jAdapter
from app.adapters.redis_adapter import RedisAdapter
from app.config import settings
from app.utils.logger import get_logger
from app.utils.metrics import SPECS_GENERATED_TOTAL

logger = get_logger(layer="router")

router = APIRouter()


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", str(uuid.uuid4()))


@router.post("/detect-gap", response_model=DetectGapResponse)
async def detect_gap(body: DetectGapRequest, request: Request) -> DetectGapResponse:
    """Analyse a failed task context and identify the missing capability."""
    trace_id = _trace_id(request)
    detector = GapDetectorService()
    try:
        result = await detector.detect_gap(
            task_context=body.task_context.model_dump(),
            failed_agents=body.failed_agents,
            failure_reasons=body.failure_reasons,
            trace_id=trace_id,
        )
        return DetectGapResponse(**result)
    except Exception as exc:
        logger.error("detect_gap_failed", trace_id=trace_id, error=str(exc), layer="router")
        raise HTTPException(status_code=500, detail={
            "error": str(exc),
            "code": "GAP_DETECTION_FAILED",
            "trace_id": trace_id,
        })


@router.post("/generate-spec", response_model=GenerateSpecResponse)
async def generate_spec(body: GenerateSpecRequest, request: Request) -> GenerateSpecResponse:
    """Generate a capability spec from a gap description, validate, and optionally sandbox-test."""
    trace_id = _trace_id(request)
    generator = SpecGeneratorService()
    validator = SpecValidatorService()
    sandbox = SandboxRunner(settings)

    last_error: str = ""
    for attempt in range(1, body.max_attempts + 1):
        try:
            spec = await generator.generate_spec(
                gap_description=body.gap_description,
                capability_type=body.capability_type,
                trace_id=trace_id,
            )
        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "spec_generation_attempt_failed",
                trace_id=trace_id,
                attempt=attempt,
                error=last_error,
                layer="router",
            )
            continue

        code = spec.get("spec_json", {}).get("code", "")
        validation = await validator.validate_all(
            code=code,
            allowed_imports=settings.allowed_imports_list,
            trace_id=trace_id,
        )

        if validation["passed"]:
            # Run sandbox test cases if code exists and has test cases
            test_cases = spec.get("spec_json", {}).get("test_cases", [])
            if code and test_cases:
                for tc in test_cases:
                    test_input = tc.get("input", {})
                    sandbox_result = await sandbox.run_test_case(code, test_input)
                    if not sandbox_result.get("success", False):
                        logger.warning(
                            "sandbox_test_failed",
                            trace_id=trace_id,
                            test_description=tc.get("description", ""),
                            error=sandbox_result.get("error", ""),
                            layer="router",
                        )

            SPECS_GENERATED_TOTAL.labels(outcome="success").inc()
            return GenerateSpecResponse(
                spec=spec,
                validation_result=ValidationResult(
                    syntax=validation["syntax"]["ok"],
                    dependencies=validation["dependencies"]["ok"],
                    safety=validation["safety"]["ok"],
                ),
                validation_score=validation["validation_score"],
                trace_id=trace_id,
            )

        last_error = (
            f"Validation failed: syntax={validation['syntax']['error']}, "
            f"deps={validation['dependencies']['error']}, "
            f"safety={validation['safety']['error']}"
        )
        logger.warning(
            "spec_validation_failed_retry",
            trace_id=trace_id,
            attempt=attempt,
            errors=last_error,
            layer="router",
        )

    SPECS_GENERATED_TOTAL.labels(outcome="failed").inc()
    raise HTTPException(status_code=422, detail={
        "error": f"Failed to generate valid spec after {body.max_attempts} attempts: {last_error}",
        "code": "SPEC_GENERATION_FAILED",
        "trace_id": trace_id,
    })


@router.post("/register", response_model=RegisterResponse)
async def register(body: RegisterRequest, request: Request) -> RegisterResponse:
    """Register a validated capability spec into MySQL, Neo4j, and publish event."""
    trace_id = _trace_id(request)
    registrar = CapabilityRegistrar(
        mysql_adapter=MySQLAdapter(),
        neo4j_adapter=Neo4jAdapter(),
        redis_adapter=RedisAdapter(),
    )
    try:
        capability_id = await registrar.register(
            spec=body.spec,
            gap_id=body.gap_id,
            validation_score=body.validation_score,
            trace_id=trace_id,
        )
        return RegisterResponse(
            capability_id=capability_id,
            capability_type=body.spec.get("capability_type", "TOOL"),
            registered=True,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("register_failed", trace_id=trace_id, error=str(exc), layer="router")
        raise HTTPException(status_code=500, detail={
            "error": str(exc),
            "code": "REGISTRATION_FAILED",
            "trace_id": trace_id,
        })
