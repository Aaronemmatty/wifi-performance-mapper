# Grid-Based Wi-Fi Performance Mapping and Monitoring System

## Purpose
The **Grid-Based Wi-Fi Performance Mapping and Monitoring System** is a diagnostic and visualization platform designed to measure Wi-Fi and network performance characteristics at predefined grid locations across a college floor plan, displaying the resulting spatial dataset as an interactive heatmap overlaid on an SVG floor map.

## Intended Metrics
The system is planned to capture and analyze the following metrics at each designated grid coordinate:
- **RSSI / Wi-Fi Signal Information**: Signal strength representing true physical Received Signal Strength Indicator in dBm where Windows APIs and hardware drivers support it. *Note: Native Windows command-line tools often report a normalized signal percentage (0–100%). Signal percentage is not mathematically equivalent to true RSSI dBm and will not be conflated or arbitrarily converted without verified calibration.*
- **SSID**: Service Set Identifier (network name).
- **BSSID**: Basic Service Set Identifier (hardware MAC address of the serving Access Point).
- **Latency**: Round-trip time (RTT) to network targets.
- **Packet Loss**: Percentage of dropped packets over a sample burst.
- **Throughput**: Effective data transfer rate (bandwidth).
- **Timestamp**: Time of measurement capture.
- **Floor / Grid Coordinate**: Spatial (X, Y) coordinate or cell identifier mapped to the floor plan.

## Development Environment
- **Operating System**: Windows PC (Native development)
- **Language & Runtime**: Python 3.14 / 3.13 (utilizing project-local `.venv`)
- **Database**: PostgreSQL (native Windows installation)
- **Backend Framework**: FastAPI (planned for future API milestones)
- **Frontend**: Plain HTML5, CSS, Vanilla JavaScript, and SVG (no heavy frontend frameworks like React or Vue)

## Current Milestone (Milestone 1)
**Milestone 1: Project Foundation + Environment Verification**
This milestone focuses strictly on establishing the project structure, verifying local toolchains, setting up virtual environment isolation, inspecting host Wi-Fi adapter/driver capabilities, and implementing safe environment verification scripts. No application backend, database schema, or UI logic is implemented in this phase.

## Future Milestones
1. Hardware / Wi-Fi Capability Verification & Driver Deep-Dive
2. Wi-Fi Measurement Engine Implementation
3. Network Performance (Latency, Loss, Throughput) Engine Implementation
4. PostgreSQL Database Schema & FastAPI Backend Service
5. Dummy Floor Plan and Grid Coordinate Mapping
6. Web Dashboard and Interactive SVG Heatmap
7. End-to-End System Integration & Testing
8. Secondary Laptop / Hardware Compatibility Verification
9. On-Site College Floor Survey & Data Collection
