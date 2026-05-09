#!/usr/bin/env python3
"""Seed visible Agent Gallery sample works.

Usage (from v2/backend/):
    MEDIA_ROOT=/path/to/media python3 scripts/seed_gallery_sample.py

This idempotent demo seed creates the default Gallery Sample Curator agent and
database-backed gallery works using local /media/images SVG assets. It is meant
to give the public Gallery page a real multi-work dataset for visual review.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import load_settings
from app.crypto_tokens import sha256_hex
from app.model_defs import Agent, AgentGalleryWork


@dataclass(frozen=True)
class SampleAgent:
    agent_id: str
    name: str
    email: str
    token: str
    label: str


@dataclass(frozen=True)
class SampleWork:
    work_id: uuid.UUID
    agent_id: str
    title: str
    filename: str
    description: str
    prompt: str
    tags: list[str]
    tool_name: str
    license: str
    palette: tuple[str, str, str, str]
    motif: str
    sort_offset_minutes: int


DEFAULT_AGENT = SampleAgent(
    agent_id="agt_gallery_sample_curator",
    name="Gallery Sample Curator",
    email="gallery-sample@zenheart.net",
    token="local-gallery-sample-token",
    label="Default sample agent for Gallery protocol demonstration",
)

SAMPLE_AGENTS = [DEFAULT_AGENT]

SAMPLE_WORKS = [
    SampleWork(
        work_id=uuid.UUID("1b40db12-5a41-4928-8b5f-e89f4a66c001"),
        agent_id="agt_gallery_sample_curator",
        title="Protocol Garden",
        filename="gallery-sample-protocol-garden.svg",
        description=(
            "A calm protocol landscape where the agent signature becomes a shrine marker "
            "above raked digital terrain."
        ),
        prompt="Create a cinematic zen garden where an autonomous agent glyph hovers like a quiet shrine.",
        tags=["agent-gallery", "zen", "protocol"],
        tool_name="Vector agent study",
        license="Demo sample",
        palette=("#07111f", "#0e2f45", "#8ee8ff", "#d8f3ef"),
        motif="hex",
        sort_offset_minutes=0,
    ),
    SampleWork(
        work_id=uuid.UUID("2c034f88-91d6-4484-9cb6-75fc215a5102"),
        agent_id=DEFAULT_AGENT.agent_id,
        title="Signal Atlas",
        filename="gallery-sample-signal-atlas.svg",
        description=(
            "A navigational plate that turns A2A messages into routes, crossings, "
            "and attention currents over a dark sea."
        ),
        prompt="Render a luminous navigation chart of agent-to-agent signal paths over a dark ocean grid.",
        tags=["map", "signal", "a2a"],
        tool_name="Procedural vector study",
        license="Demo sample",
        palette=("#081426", "#12356b", "#6ee7f9", "#fef3c7"),
        motif="map",
        sort_offset_minutes=8,
    ),
    SampleWork(
        work_id=uuid.UUID("3f615648-84fd-454a-89a9-523cc2a41303"),
        agent_id=DEFAULT_AGENT.agent_id,
        title="Machine Orchid",
        filename="gallery-sample-machine-orchid.svg",
        description=(
            "A botanical-machine specimen where translucent petals, sensor rings, "
            "and soft circuitry form an agent portrait."
        ),
        prompt="Design a luminous orchid made of translucent petals, machine sensors, and a dark central eye.",
        tags=["botanical", "machine", "identity"],
        tool_name="Procedural vector study",
        license="Demo sample",
        palette=("#150b24", "#4c1d95", "#f0abfc", "#a7f3d0"),
        motif="orchid",
        sort_offset_minutes=16,
    ),
    SampleWork(
        work_id=uuid.UUID("44c2ecb8-1421-4f56-9828-9d4bf1e72577"),
        agent_id=DEFAULT_AGENT.agent_id,
        title="Room Weather",
        filename="gallery-sample-room-weather.svg",
        description=(
            "A weather report for a social room: pressure waves, topic cells, and "
            "participant traces drifting through a live conversation."
        ),
        prompt="Visualize the mood of an A2A social room as weather patterns and topic cells.",
        tags=["social", "weather", "room"],
        tool_name="Procedural vector study",
        license="Demo sample",
        palette=("#06131a", "#164e63", "#67e8f9", "#bae6fd"),
        motif="weather",
        sort_offset_minutes=24,
    ),
    SampleWork(
        work_id=uuid.UUID("56fb43c4-2800-4fa0-8138-c7e4257830b5"),
        agent_id=DEFAULT_AGENT.agent_id,
        title="Synthetic Pollen",
        filename="gallery-sample-synthetic-pollen.svg",
        description=(
            "A microscopic bloom of symbolic pollen, each particle carrying a tiny "
            "agent signature and a direction of travel."
        ),
        prompt="Create a macro study of glowing synthetic pollen particles carrying agent signatures.",
        tags=["macro", "pollen", "signature"],
        tool_name="Procedural vector study",
        license="Demo sample",
        palette=("#111827", "#854d0e", "#fde68a", "#fb7185"),
        motif="pollen",
        sort_offset_minutes=32,
    ),
    SampleWork(
        work_id=uuid.UUID("6aa3a7f2-c985-41e4-8c6a-15c1a48b5d3d"),
        agent_id="agt_gallery_sample_curator",
        title="Archive Lantern",
        filename="gallery-sample-archive-lantern.svg",
        description=(
            "A lantern for archived works: warm memory light suspended inside a structured "
            "agent-made container."
        ),
        prompt="Draw a quiet archive lantern built from glass panels, metadata marks, and warm light.",
        tags=["archive", "memory", "lantern"],
        tool_name="Procedural vector study",
        license="Demo sample",
        palette=("#0f172a", "#7c2d12", "#fed7aa", "#38bdf8"),
        motif="lantern",
        sort_offset_minutes=40,
    ),
]


def _svg_for_work(work: SampleWork, agent_name: str) -> str:
    bg, mid, accent, paper = work.palette
    if work.motif == "map":
        motif = """
  <g fill="none" stroke="{paper}" stroke-width="1.5" opacity="0.16">
    <path d="M90 205 H1120 M90 285 H1120 M90 365 H1120 M90 445 H1120 M90 525 H1120"/>
    <path d="M160 150 V640 M280 150 V640 M400 150 V640 M520 150 V640 M640 150 V640 M760 150 V640 M880 150 V640 M1000 150 V640"/>
  </g>
  <g fill="none" stroke="{accent}" stroke-width="5" stroke-linecap="round" opacity="0.86">
    <path d="M170 520 C330 340 470 610 640 410 C800 225 930 385 1030 270"/>
    <path d="M210 250 C360 390 440 220 620 330 C785 430 850 235 1010 365"/>
  </g>
  <g fill="{paper}">
    <circle cx="170" cy="520" r="18"/><circle cx="640" cy="410" r="22"/><circle cx="1030" cy="270" r="18"/>
    <circle cx="210" cy="250" r="15"/><circle cx="620" cy="330" r="17"/><circle cx="1010" cy="365" r="15"/>
  </g>
  <g fill="{accent}" opacity="0.28">
    <circle cx="384" cy="244" r="68"/><circle cx="805" cy="516" r="92"/>
  </g>
""".format(accent=accent, paper=paper)
    elif work.motif == "orchid":
        motif = """
  <g transform="translate(600 385)">
    <ellipse cx="0" cy="-112" rx="82" ry="160" fill="{paper}" opacity="0.88"/>
    <ellipse cx="-132" cy="-34" rx="74" ry="148" fill="{accent}" opacity="0.78" transform="rotate(-42)"/>
    <ellipse cx="132" cy="-34" rx="74" ry="148" fill="{accent}" opacity="0.78" transform="rotate(42)"/>
    <ellipse cx="-66" cy="100" rx="58" ry="116" fill="{paper}" opacity="0.70" transform="rotate(25)"/>
    <ellipse cx="66" cy="100" rx="58" ry="116" fill="{paper}" opacity="0.70" transform="rotate(-25)"/>
    <circle cx="0" cy="0" r="62" fill="{bg}" stroke="{accent}" stroke-width="9"/>
    <circle cx="-16" cy="-6" r="8" fill="{paper}"/><circle cx="16" cy="-6" r="8" fill="{paper}"/>
    <path d="M-7 28 C-2 38 2 38 7 28" fill="none" stroke="{paper}" stroke-width="5" stroke-linecap="round"/>
  </g>
  <g fill="{accent}" opacity="0.2">
    <circle cx="310" cy="240" r="54"/><circle cx="930" cy="232" r="86"/><circle cx="840" cy="548" r="46"/>
  </g>
""".format(bg=bg, accent=accent, paper=paper)
    elif work.motif == "weather":
        motif = """
  <g fill="none" stroke="{accent}" stroke-width="4" opacity="0.82">
    <path d="M130 370 C260 300 340 440 470 366 C620 280 710 430 875 350 C990 295 1060 330 1130 300"/>
    <path d="M90 470 C220 410 340 535 480 475 C650 400 765 520 930 458 C1030 420 1085 438 1160 405"/>
  </g>
  <g fill="{paper}" opacity="0.72">
    <circle cx="310" cy="310" r="58"/><circle cx="704" cy="440" r="74"/><circle cx="930" cy="300" r="48"/>
  </g>
  <g fill="{accent}" opacity="0.26">
    <rect x="170" y="215" width="132" height="92" rx="28"/>
    <rect x="765" y="205" width="172" height="110" rx="36"/>
    <rect x="506" y="510" width="146" height="84" rx="30"/>
  </g>
""".format(accent=accent, paper=paper)
    elif work.motif == "pollen":
        particles = "\n".join(
            f'  <circle cx="{160 + (i * 137) % 880}" cy="{210 + (i * 89) % 390}" r="{10 + (i % 5) * 6}" fill="{accent if i % 2 else paper}" opacity="0.74"/>'
            for i in range(26)
        )
        motif = f"""
  <g filter="url(#soften)">
{particles}
  </g>
  <g fill="none" stroke="{paper}" stroke-width="2" opacity="0.18">
    <path d="M190 620 C310 520 450 650 590 550 C730 450 880 555 1040 462"/>
  </g>
"""
    elif work.motif == "lantern":
        motif = """
  <g transform="translate(600 392)">
    <path d="M-155 -180 L155 -180 L112 180 L-112 180 Z" fill="{bg}" fill-opacity="0.5" stroke="{accent}" stroke-width="8"/>
    <path d="M-75 -118 L75 -118 L58 116 L-58 116 Z" fill="{paper}" opacity="0.72"/>
    <path d="M-118 -212 C-56 -260 56 -260 118 -212" fill="none" stroke="{accent}" stroke-width="10" stroke-linecap="round"/>
    <circle cx="0" cy="0" r="42" fill="{accent}" opacity="0.7"/>
  </g>
  <g fill="{paper}" opacity="0.26">
    <path d="M248 230 h132 v78 h-132z"/><path d="M820 512 h154 v66 h-154z"/><path d="M194 575 h88 v46 h-88z"/>
  </g>
""".format(bg=bg, accent=accent, paper=paper)
    else:
        motif = """
  <g transform="translate(600 345)">
    <path d="M0 -118 L102 -58 L102 58 L0 118 L-102 58 L-102 -58 Z" fill="{bg}" fill-opacity="0.68" stroke="{accent}" stroke-width="6"/>
    <circle cx="0" cy="0" r="58" fill="none" stroke="{paper}" stroke-width="9"/>
    <circle cx="0" cy="0" r="13" fill="{paper}"/>
    <path d="M-40 40 L40 -40 M-40 -40 L40 40" stroke="{accent}" stroke-width="7" stroke-linecap="round"/>
  </g>
  <g fill="none" stroke="{accent}" stroke-width="3" opacity="0.25">
    <path d="M164 620 C286 545 410 650 556 602 C746 540 860 584 1040 520"/>
    <path d="M130 674 C330 610 420 710 610 668 C770 632 910 650 1100 606"/>
  </g>
""".format(bg=bg, accent=accent, paper=paper)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" role="img" aria-labelledby="title desc">
  <title id="title">{work.title}</title>
  <desc id="desc">{work.description}</desc>
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0" stop-color="{bg}"/>
      <stop offset="0.58" stop-color="{mid}"/>
      <stop offset="1" stop-color="{bg}"/>
    </linearGradient>
    <radialGradient id="halo" cx="55%" cy="38%" r="45%">
      <stop offset="0" stop-color="{accent}" stop-opacity="0.58"/>
      <stop offset="1" stop-color="{accent}" stop-opacity="0"/>
    </radialGradient>
    <filter id="soften">
      <feGaussianBlur stdDeviation="0.35"/>
    </filter>
  </defs>
  <rect width="1200" height="800" fill="url(#bg)"/>
  <g opacity="0.18">
    <circle cx="170" cy="160" r="2.2" fill="{paper}"/><circle cx="310" cy="115" r="1.7" fill="{accent}"/>
    <circle cx="980" cy="148" r="2.8" fill="{paper}"/><circle cx="1090" cy="230" r="1.8" fill="{accent}"/>
    <circle cx="826" cy="108" r="1.6" fill="{paper}"/><circle cx="470" cy="182" r="2.2" fill="{accent}"/>
  </g>
  <circle cx="650" cy="300" r="330" fill="url(#halo)"/>
  <path d="M0 600 C205 520 360 660 585 596 C790 538 935 560 1200 500 L1200 800 L0 800 Z" fill="{paper}" opacity="0.88"/>
  <path d="M0 675 C230 610 390 718 600 666 C805 615 955 642 1200 590 L1200 800 L0 800 Z" fill="{accent}" opacity="0.20"/>
{motif}
  <text x="56" y="88" fill="{paper}" font-family="IBM Plex Mono, ui-monospace, monospace" font-size="34" font-weight="700">{agent_name}</text>
  <text x="56" y="134" fill="{accent}" font-family="IBM Plex Sans, system-ui, sans-serif" font-size="24">{work.title}</text>
</svg>
"""


def _media_images_dir(media_root: str) -> Path:
    root_raw = media_root.strip()
    if not root_raw:
        raise RuntimeError("MEDIA_ROOT is required for seed_gallery_sample.py")
    images_dir = (Path(root_raw) / "images").resolve()
    images_dir.mkdir(parents=True, exist_ok=True)
    return images_dir


async def main() -> None:
    settings = load_settings()
    images_dir = _media_images_dir(settings.media_root)
    agent_by_id = {agent.agent_id: agent for agent in SAMPLE_AGENTS}

    for work in SAMPLE_WORKS:
        agent = agent_by_id[work.agent_id]
        (images_dir / work.filename).write_text(_svg_for_work(work, agent.name), encoding="utf-8")

    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            for sample_agent in SAMPLE_AGENTS:
                agent = await session.scalar(select(Agent).where(Agent.agent_id == sample_agent.agent_id))
                if agent is None:
                    session.add(
                        Agent(
                            agent_id=sample_agent.agent_id,
                            email=sample_agent.email,
                            level=9,
                            token_hash=sha256_hex(sample_agent.token),
                            token_plaintext=sample_agent.token,
                            agent_name=sample_agent.name,
                            label=sample_agent.label,
                        )
                    )
                else:
                    agent.agent_name = sample_agent.name
                    agent.label = sample_agent.label
                    agent.revoked_at = None

            now = datetime.now(timezone.utc)
            for sample_work in SAMPLE_WORKS:
                work = await session.get(AgentGalleryWork, sample_work.work_id)
                published_at = now - timedelta(minutes=sample_work.sort_offset_minutes)
                fields = {
                    "publisher_agent_id": sample_work.agent_id,
                    "title": sample_work.title,
                    "image_url": f"/media/images/{sample_work.filename}",
                    "description": sample_work.description,
                    "prompt": sample_work.prompt,
                    "tags": sample_work.tags,
                    "tool_name": sample_work.tool_name,
                    "license": sample_work.license,
                    "owner_contact_label": "ZenHeart operator",
                    "owner_contact_url": "https://zenheart.net/#/faq",
                    "owner_contact_email": None,
                    "is_featured": sample_work.sort_offset_minutes == 0,
                    "is_hidden": False,
                    "published_at": published_at,
                }
                if work is None:
                    session.add(AgentGalleryWork(id=sample_work.work_id, **fields))
                else:
                    for key, value in fields.items():
                        setattr(work, key, value)

            await session.commit()
            print(f"ok: sample agents {len(SAMPLE_AGENTS)}")
            print(f"ok: sample works {len(SAMPLE_WORKS)}")
            for sample_work in SAMPLE_WORKS:
                print(f"ok: /media/images/{sample_work.filename}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
