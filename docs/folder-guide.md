# TRAVIO — Project Folder Guide

## 1. Project Overview

TRAVIO is an AI-powered travel-planning system built with Python, FastAPI, LangGraph, and Supabase.

This document explains the purpose of each directory and where team members should place their code.

## 2. Project Structure

```text
travio/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── router.py
│   │   │   └── endpoints/
│   │   ├── agents/
│   │   ├── graph/
│   │   ├── domain/
│   │   ├── providers/
│   │   │   └── mocks/
│   │   ├── planner/
│   │   ├── verification/
│   │   ├── persistence/
│   │   ├── booking/
│   │   └── core/
│   └── requirements.txt
├── frontend/
├── supabase/
│   ├── migrations/
│   └── seed.sql
├── tests/
│   ├── unit/
│   ├── agents/
│   ├── api/
│   ├── integration/
│   └── e2e/
├── docs/
│   ├── blueprint.md
│   ├── team-responsibilities.md
│   ├── folder-guide.md
│   ├── user-stories.md
│   └── feature-plan.md
├── .env.example
├── .gitignore
└── README.md
```

## 3. Backend Directories

### `backend/app/`

Contains the main Python backend application and its business logic.

- **`main.py`** — Creates the FastAPI application and registers the API router.
- **`api/`** — Defines the HTTP API endpoints and routes.
- **`api/endpoints/`** — Contains endpoint modules grouped by feature, such as trips, itinerary, feedback, bookings, and preferences.
- **`agents/`** — Contains specialized AI agents, such as the supervisor, transport agent, accommodation agent, and experiences agent.
- **`graph/`** — Defines the LangGraph workflow, including how agents and other processing steps connect.
- **`domain/`** — Contains shared data models, Pydantic schemas, workflow state definitions, enums, and core business rules.
- **`providers/`** — Contains adapters that communicate with external travel data providers or services.
- **`providers/mocks/`** — Contains mock providers for development and testing when real APIs are unavailable.
- **`planner/`** — Builds and updates travel itineraries, including schedules, budget calculations, and activity ordering.
- **`verification/`** — Validates travel options and itineraries against requirements, constraints, and available evidence.
- **`persistence/`** — Contains the code responsible for saving, retrieving, and updating application data in Supabase.
- **`booking/`** — Manages booking workflows, booking status, and user approval before booking-related actions.
- **`core/`** — Contains application-wide configuration and shared infrastructure, such as environment settings.

### `backend/requirements.txt`

Lists the Python dependencies needed to run the backend.

## 4. Frontend

### `frontend/`

Contains the user interface for TRAVIO.

The frontend communicates with the backend API to submit travel requests, display itineraries, collect feedback, and show booking information.

The frontend is a shared project responsibility. Team members should coordinate UI changes with the backend API contracts.

## 5. Database and Supabase

### `supabase/`

Contains database setup and seed data for Supabase.

- **`migrations/`** — SQL migration files for creating or updating database tables, relationships, indexes, and database policies.
- **`seed.sql`** — Initial or sample data used for development and testing.

### `persistence/` vs. `supabase/migrations/`

These directories have different responsibilities:

- `persistence/` contains Python code that interacts with the database.
- `supabase/migrations/` contains SQL scripts that define or change the database structure.

For example, a Python repository might save a trip, while a migration creates the table where that trip is stored.

## 6. Tests

### `tests/`

Contains automated tests for the application.

- **`unit/`** — Tests individual functions and components.
- **`agents/`** — Tests AI agent behavior and outputs.
- **`api/`** — Tests API endpoints and request/response validation.
- **`integration/`** — Tests interactions between components, providers, and persistence.
- **`e2e/`** — Tests complete user workflows from request submission to itinerary generation and feedback.

## 7. Documentation

### `docs/`

Contains project documentation shared by all team members.

- **`blueprint.md`** — Describes the architecture, workflow, and technical design.
- **`team-responsibilities.md`** — Defines the responsibilities of the five team members.
- **`folder-guide.md`** — Explains the project directory structure.
- **`user-stories.md`** — Documents user stories and expected behavior.
- **`feature-plan.md`** — Describes planned features and implementation tasks.

## 8. Root Files

- **`.env.example`** — Lists the environment variables required by the application using placeholder values. Never put real secrets in this file.
- **`.gitignore`** — Prevents temporary files, virtual environments, local configuration, and secrets from being committed.
- **`README.md`** — Provides the project overview, setup instructions, and instructions for running the application.
