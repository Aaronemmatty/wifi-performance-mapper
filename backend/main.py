"""
backend/main.py
FastAPI Application and REST API Layer for Wi-Fi Performance Mapper.

Exposes endpoints for survey sessions and multi-metric measurement persistence.
Decoupled from physical measurement collection and database internals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
import psycopg2

from backend.repository import (
    create_session,
    get_session,
    list_sessions,
    create_measurement,
    get_measurement,
    list_measurements,
)


# ----------------------------------------------------------------------
# Pydantic Request & Response Models
# ----------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"


class SessionCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64, description="Unique session identifier")
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable survey name")
    floor: str = Field(..., min_length=1, max_length=64, description="Floor plan identifier")
    notes: Optional[str] = Field(default=None, description="Optional survey notes or observations")

    @field_validator("session_id", "name", "floor")
    @classmethod
    def check_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field cannot be empty or only whitespace")
        return v.strip()


class SessionResponse(BaseModel):
    session_id: str
    name: str
    floor: str
    created_at: datetime
    notes: Optional[str] = None


class MeasurementCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64, description="Survey session foreign key")
    floor: str = Field(..., min_length=1, max_length=64, description="Floor plan identifier")
    x: float = Field(..., description="X grid/floor coordinate")
    y: float = Field(..., description="Y grid/floor coordinate")

    # RF & Network Metrics (Nullable to preserve absence vs. zero)
    rssi_dbm: Optional[int] = Field(default=None, le=0, description="Signal strength in dBm (<= 0)")
    signal_percent: Optional[int] = Field(default=None, ge=0, le=100, description="Signal quality (0-100)")
    latency_ms: Optional[float] = Field(default=None, ge=0.0, description="RTT latency in milliseconds (>= 0)")
    packet_loss_percent: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Packet loss % (0-100)")
    throughput_mbps: Optional[float] = Field(default=None, ge=0.0, description="Application throughput in Mbps (>= 0)")

    # Wi-Fi Context Metadata
    ssid: Optional[str] = Field(default=None, max_length=64)
    bssid: Optional[str] = Field(default=None, max_length=32)
    channel: Optional[int] = Field(default=None)
    frequency_mhz: Optional[float] = Field(default=None)
    radio_type: Optional[str] = Field(default=None, max_length=64)
    adapter_name: Optional[str] = Field(default=None, max_length=128)
    driver_version: Optional[str] = Field(default=None, max_length=64)

    # Aggregation & Temporal
    sample_count: int = Field(default=1, ge=1, description="Number of aggregated probe samples (>= 1)")
    timestamp: Optional[datetime] = Field(default=None, description="Measurement capture timestamp")

    @field_validator("session_id", "floor")
    @classmethod
    def check_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Field cannot be empty or only whitespace")
        return v.strip()


class MeasurementResponse(BaseModel):
    id: int
    session_id: str
    floor: str
    x: float
    y: float
    rssi_dbm: Optional[int] = None
    signal_percent: Optional[int] = None
    latency_ms: Optional[float] = None
    packet_loss_percent: Optional[float] = None
    throughput_mbps: Optional[float] = None
    ssid: Optional[str] = None
    bssid: Optional[str] = None
    channel: Optional[int] = None
    frequency_mhz: Optional[float] = None
    radio_type: Optional[str] = None
    adapter_name: Optional[str] = None
    driver_version: Optional[str] = None
    sample_count: int
    timestamp: datetime
    created_at: datetime


# ----------------------------------------------------------------------
# FastAPI Application Factory
# ----------------------------------------------------------------------

def create_app(database_url: Optional[str] = None, is_test: bool = False) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="Grid-Based Wi-Fi Performance Mapping API",
        description="HTTP REST API for survey sessions and Wi-Fi performance measurement persistence.",
        version="0.1.0",
    )

    @app.get(
        "/health",
        response_model=HealthResponse,
        summary="API Health Check",
        tags=["System"],
    )
    def health_check() -> Dict[str, str]:
        """Simple liveness probe confirming API availability."""
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Session Routes
    # ------------------------------------------------------------------

    @app.post(
        "/sessions",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create Survey Session",
        tags=["Sessions"],
    )
    def create_survey_session(payload: SessionCreateRequest) -> Dict[str, Any]:
        """Create a new survey session for data collection."""
        try:
            session = create_session(
                session_id=payload.session_id,
                name=payload.name,
                floor=payload.floor,
                notes=payload.notes,
                database_url=database_url,
                is_test=is_test,
            )
            return session
        except ValueError as ve:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
        except psycopg2.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Session with session_id '{payload.session_id}' already exists.",
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal database error occurred while creating session.",
            )

    @app.get(
        "/sessions",
        response_model=List[SessionResponse],
        summary="List Survey Sessions",
        tags=["Sessions"],
    )
    def get_survey_sessions() -> List[Dict[str, Any]]:
        """Retrieve all survey sessions ordered chronologically descending."""
        try:
            return list_sessions(database_url=database_url, is_test=is_test)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal database error occurred while retrieving sessions.",
            )

    @app.get(
        "/sessions/{session_id}",
        response_model=SessionResponse,
        summary="Get Survey Session by ID",
        tags=["Sessions"],
    )
    def get_survey_session(session_id: str) -> Dict[str, Any]:
        """Retrieve a specific survey session by its unique session_id."""
        try:
            session = get_session(session_id=session_id.strip(), database_url=database_url, is_test=is_test)
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Session '{session_id}' not found.",
                )
            return session
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal database error occurred while retrieving session.",
            )

    # ------------------------------------------------------------------
    # Measurement Routes
    # ------------------------------------------------------------------

    @app.post(
        "/measurements",
        response_model=MeasurementResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create Measurement Record",
        tags=["Measurements"],
    )
    def create_measurement_record(payload: MeasurementCreateRequest) -> Dict[str, Any]:
        """
        Record a new historical measurement point.
        Every POST appends a new record to support time-series historical data.
        """
        try:
            measurement = create_measurement(
                session_id=payload.session_id,
                floor=payload.floor,
                x=payload.x,
                y=payload.y,
                rssi_dbm=payload.rssi_dbm,
                signal_percent=payload.signal_percent,
                latency_ms=payload.latency_ms,
                packet_loss_percent=payload.packet_loss_percent,
                throughput_mbps=payload.throughput_mbps,
                ssid=payload.ssid,
                bssid=payload.bssid,
                channel=payload.channel,
                frequency_mhz=payload.frequency_mhz,
                radio_type=payload.radio_type,
                adapter_name=payload.adapter_name,
                driver_version=payload.driver_version,
                sample_count=payload.sample_count,
                timestamp=payload.timestamp,
                database_url=database_url,
                is_test=is_test,
            )
            return measurement
        except ValueError as ve:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
        except psycopg2.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid measurement: referenced session '{payload.session_id}' does not exist.",
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal database error occurred while creating measurement.",
            )

    @app.get(
        "/measurements",
        response_model=List[MeasurementResponse],
        summary="List Measurements with Optional Filtering",
        tags=["Measurements"],
    )
    def get_measurements(
        session_id: Optional[str] = Query(default=None, description="Filter by session ID"),
        floor: Optional[str] = Query(default=None, description="Filter by floor identifier"),
        x: Optional[float] = Query(default=None, description="Filter by X coordinate"),
        y: Optional[float] = Query(default=None, description="Filter by Y coordinate"),
    ) -> List[Dict[str, Any]]:
        """Retrieve historical measurement records with optional spatial and session filtering."""
        try:
            return list_measurements(
                session_id=session_id.strip() if session_id else None,
                floor=floor.strip() if floor else None,
                x=x,
                y=y,
                database_url=database_url,
                is_test=is_test,
            )
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal database error occurred while retrieving measurements.",
            )

    @app.get(
        "/measurements/{measurement_id}",
        response_model=MeasurementResponse,
        summary="Get Measurement by ID",
        tags=["Measurements"],
    )
    def get_measurement_by_id(measurement_id: int) -> Dict[str, Any]:
        """Retrieve a specific measurement record by its primary key ID."""
        try:
            record = get_measurement(measurement_id=measurement_id, database_url=database_url, is_test=is_test)
            if not record:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Measurement with ID {measurement_id} not found.",
                )
            return record
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal database error occurred while retrieving measurement.",
            )

    return app


# Default ASGI application instance
app = create_app()
