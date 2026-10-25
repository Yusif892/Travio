-- 0001_core_schema.sql
-- Owner: Person 5 (persistence).  Plain PostgreSQL, no Supabase objects.
--
-- Scope: trips, itinerary versions, approvals, long-term preferences, feedback.
-- Bookings arrive in 0002.  LangGraph checkpoint tables are NOT defined here:
-- they are created by PostgresSaver.setup() (see persistence/checkpointer.py).
--
-- Ownership model: there is no users table yet (no auth in the project).
-- user_id is an opaque TEXT identifier supplied by the API (X-User-Id / body).
-- Isolation is enforced in the application layer (every query filters by
-- user_id) and backed by NOT NULL constraints here.

create extension if not exists pgcrypto;  -- gen_random_uuid()

create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

-- ---------------------------------------------------------------------
-- trips : persistent form of TripRecord (domain/schemas.py)
-- ---------------------------------------------------------------------
create table trips (
  trip_id           uuid primary key default gen_random_uuid(),
  thread_id         text not null unique,          -- LangGraph thread (NOT equal to trip_id)
  user_id           text not null check (length(user_id) between 1 and 128),

  status            text not null default 'draft' check (status in (
                      'draft', 'planning', 'awaiting_approval', 'approved',
                      'rejected', 'booking', 'booked', 'partially_booked',
                      'failed', 'cancelled')),

  -- denormalised from trip_request for history listing / filtering
  origin            text,
  destination       text,
  departure_date    date,
  return_date       date,
  budget            numeric(12,2) check (budget is null or budget > 0),
  travelers         integer       check (travelers is null or travelers > 0),

  -- mirrors of TripRecord / TravelState fields (owned by other members' code)
  trip_request      jsonb not null default '{}'::jsonb,
  messages          jsonb not null default '[]'::jsonb,
  tasks             jsonb not null default '[]'::jsonb,
  transport_options jsonb not null default '[]'::jsonb,
  lodging_options   jsonb not null default '[]'::jsonb,
  experience_options jsonb not null default '[]'::jsonb,
  verification      jsonb,
  itinerary         jsonb,                         -- latest itinerary (history in itinerary_versions)
  errors            jsonb not null default '[]'::jsonb,

  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  check (return_date is null or departure_date is null or return_date >= departure_date),
  check (jsonb_typeof(messages) = 'array' and jsonb_typeof(tasks) = 'array'
         and jsonb_typeof(errors) = 'array')
);

create index trips_user_created_idx on trips (user_id, created_at desc);
create index trips_user_status_idx  on trips (user_id, status);

create trigger trips_set_updated_at before update on trips
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------
-- itinerary_versions : immutable snapshots (Person 4's Itinerary.version)
-- Approvals and bookings point at (trip_id, version) + content_hash.
-- ---------------------------------------------------------------------
create table itinerary_versions (
  trip_id       uuid not null references trips(trip_id) on delete cascade,
  version       integer not null check (version > 0),
  content       jsonb not null,
  content_hash  text not null check (content_hash ~ '^[0-9a-f]{64}$'),  -- sha256 hex
  total_cost    numeric(12,2) check (total_cost is null or total_cost >= 0),
  currency      char(3),
  created_at    timestamptz not null default now(),
  primary key (trip_id, version)
);

-- snapshots are immutable: no UPDATE allowed
create or replace function forbid_update() returns trigger language plpgsql as $$
begin
  raise exception '% rows are immutable', tg_table_name;
end $$;

create trigger itinerary_versions_immutable before update on itinerary_versions
  for each row execute function forbid_update();

-- ---------------------------------------------------------------------
-- trip_approvals : decision tied to the EXACT itinerary version approved
-- ---------------------------------------------------------------------
create table trip_approvals (
  approval_id        uuid primary key default gen_random_uuid(),
  trip_id            uuid not null,
  user_id            text not null,
  itinerary_version  integer not null,
  content_hash       text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  decision           text not null check (decision in ('approved', 'rejected')),
  comment            text,
  created_at         timestamptz not null default now(),
  foreign key (trip_id, itinerary_version)
    references itinerary_versions (trip_id, version) on delete cascade
);

create index trip_approvals_trip_idx on trip_approvals (trip_id, created_at desc);

create trigger trip_approvals_immutable before update on trip_approvals
  for each row execute function forbid_update();

-- ---------------------------------------------------------------------
-- preferences : long-term memory per user; optional per-trip override
-- ---------------------------------------------------------------------
create table preferences (
  preference_id uuid primary key default gen_random_uuid(),
  user_id       text not null check (length(user_id) between 1 and 128),
  trip_id       uuid references trips(trip_id) on delete cascade,  -- null = global
  category      text not null default 'general',
  key           text not null,
  value         jsonb not null,
  source        text not null default 'user' check (source in ('user', 'feedback', 'inferred')),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create unique index preferences_global_uq on preferences (user_id, key) where trip_id is null;
create unique index preferences_trip_uq   on preferences (user_id, trip_id, key) where trip_id is not null;
create index preferences_user_category_idx on preferences (user_id, category);

create trigger preferences_set_updated_at before update on preferences
  for each row execute function set_updated_at();

-- ---------------------------------------------------------------------
-- trip_feedback : raw feedback + Person 4's parsed intent
-- ---------------------------------------------------------------------
create table trip_feedback (
  feedback_id        uuid primary key default gen_random_uuid(),
  trip_id            uuid not null references trips(trip_id) on delete cascade,
  user_id            text not null,
  itinerary_version  integer,                       -- version the user was looking at
  message            text not null check (length(message) > 0),
  parsed             jsonb,
  created_at         timestamptz not null default now(),
  foreign key (trip_id, itinerary_version)
    references itinerary_versions (trip_id, version) on delete cascade
);

create index trip_feedback_trip_idx on trip_feedback (trip_id, created_at desc);