#!/usr/bin/env python3
"""Generate 1-page role-tailored CVs matching Mohamed_Ahmed-general.pdf formatting."""
from __future__ import annotations

import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
CVS_DIR = ROOT / "cvs"

BASE_CSS = """
@page {
    size: A4;
    margin: 8.5mm 11mm 8.5mm 11mm;
}
* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}
body {
    font-family: 'Helvetica Neue', Helvetica, Arial, 'Liberation Sans', sans-serif;
    font-size: 9.0pt;
    line-height: 1.24;
    color: #000;
    background: #fff;
}
a {
    color: #0000ee;
    text-decoration: none;
}
.header {
    text-align: center;
    margin-bottom: 6px;
}
.header h1 {
    font-size: 19.5pt;
    font-weight: 700;
    letter-spacing: 0.2px;
    line-height: 1.15;
}
.header .subtitle {
    font-size: 11.2pt;
    font-weight: 700;
    margin-top: 1px;
    margin-bottom: 2px;
}
.header .contact {
    font-size: 9.0pt;
    line-height: 1.25;
}
.section {
    margin-top: 5px;
}
.section-title {
    font-size: 10.2pt;
    font-weight: 700;
    text-transform: uppercase;
    border-bottom: 0.8px solid #000;
    padding-bottom: 1px;
    margin-bottom: 3.5px;
}
.skills-list p {
    margin-bottom: 1.8px;
}
.entry {
    margin-bottom: 4.5px;
}
.entry-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-weight: 700;
    font-size: 9.2pt;
}
.entry-header .right {
    font-weight: 400;
    font-size: 9.0pt;
}
.entry-sub {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 8.9pt;
    margin-bottom: 1.5px;
}
ul {
    margin-left: 14px;
}
li {
    margin-bottom: 1.2px;
}
.edu-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}
"""

CVS_SPEC = {
    "Mohamed_Ahmed-Backend.pdf": {
        "role": "Backend Developer & Software Engineer",
        "profile": (
            "Backend Software Engineer with 1.5+ years of combined experience building robust RESTful/GraphQL APIs, "
            "asynchronous service architectures, and optimized database solutions. Strong technical foundation in Node.js, "
            "Express, Python, FastAPI, Django, PostgreSQL, Redis, Docker, and automated testing with pytest and Jest."
        ),
        "skills": [
            ("Languages & Core", "Python, JavaScript (ES6+), TypeScript, SQL, Bash, C++, Data Structures, Algorithms, OS, Networking."),
            ("Backend Frameworks & APIs", "Node.js, Express.js, FastAPI, Django, RESTful APIs, GraphQL, gRPC, Webhooks, WebSockets, Microservices."),
            ("Databases & In-Memory", "PostgreSQL, MySQL, MongoDB, Redis (Redlock Concurrency), BullMQ Asynchronous Queues, Schema Optimization."),
            ("DevOps, Cloud & QA", "Docker, Kubernetes (K3s), AWS (EC2, S3), Azure, Git/GitHub Actions CI/CD, pytest, Jest, Linux/Unix Administration."),
        ],
        "experience": [
            {
                "title": "Freelance Backend & Full Stack Software Engineer",
                "right": "Oct 2025 – Present (1 Year)",
                "sub": "Independent Software Contractor, Egypt",
                "sub_right": "",
                "bullets": [
                    "Architected RESTful backend services and normalized PostgreSQL/MongoDB database schemas for client operations.",
                    "Implemented secure authentication, role-based access control (RBAC), and transactional integrity across all endpoints.",
                    "Integrated third-party payment gateways (Paymob/Fawry) and asynchronous webhooks for real-time order processing.",
                    "Optimized database queries, eliminating slow bottlenecks and ensuring sub-100ms response times under concurrent loads.",
                ],
            },
            {
                "title": "Open Source Core Contributor — Cantera Scientific Engine",
                "right": "Active Contributor",
                "sub": "Python, C++, Linux Environments, CI/CD Automated Pipelines",
                "sub_right": '<a href="https://github.com/Cantera/cantera/pulls?q=author:hazalkoom">Pull Requests</a>',
                "bullets": [
                    "Contributed core backend bug fixes and maintenance to an enterprise-grade scientific computing library on GitHub.",
                    "Resolved memory leaks, execution bugs, and toolchain failures across GitHub Actions CI/CD matrix build pipelines.",
                ],
            },
            {
                "title": "Software Engineering Trainee — NTI Immersive Program",
                "right": "Jun 2025 – Oct 2025 (4 Months)",
                "sub": "National Telecommunication Institute (NTI), Egypt",
                "sub_right": "",
                "bullets": [
                    "Completed a 210-hour intensive track focused on backend system architecture, API design, and relational database systems.",
                    "Collaborated in Agile sprints to build backend microservices with Node.js, Express, and PostgreSQL.",
                ],
            },
        ],
        "projects": [
            {
                "title": "SmartCart Full-Stack E-Commerce Backend Engine",
                "right": '<a href="https://github.com/hazalkoom/smartCart">Source Code</a>',
                "sub": "TypeScript, Node.js, Express.js, PostgreSQL, MongoDB, Redis, Docker, BullMQ, Paymob",
                "bullets": [
                    "Engineered 50+ RESTful APIs managing product catalogs, shopping carts, order lifecycles, and payment processing.",
                    "Configured asynchronous task queues with BullMQ/Redis and maintained 200+ Jest automated tests for system reliability.",
                ],
            },
            {
                "title": "AeroLock — Real-Time Distributed Services Engine",
                "right": '<a href="https://github.com/hazalkoom/AeroLock">Source Code</a>',
                "sub": "Python, FastAPI, gRPC, PostgreSQL, Redis Redlock, WebSockets, Azure, K3s",
                "bullets": [
                    "Developed asynchronous backend microservices implementing Redis distributed locking for multi-node concurrency control.",
                    "Engineered high-throughput gRPC and WebSocket communication channels with automated containerized deployment.",
                ],
            },
            {
                "title": "RealEstate Engine — Modular Backend Monolith",
                "right": '<a href="https://github.com/hazalkoom/real-estate-platform">Source Code</a>',
                "sub": "Python, Django, PostgreSQL, GraphQL, pytest, Qdrant Vector DB",
                "bullets": [
                    "Developed a property marketplace backend with relational integrity and Qdrant semantic vector search capabilities.",
                    "Eliminated N+1 query execution bottlenecks using GraphQL DataLoaders and validated core domain logic with pytest.",
                ],
            },
        ],
    },

    "Mohamed_Ahmed-Full_Stack.pdf": {
        "role": "Full Stack Software Engineer",
        "profile": (
            "Full Stack Software Engineer with 1.5+ years of combined experience delivering end-to-end web applications, "
            "responsive SPAs, and scalable backend APIs. Proficient in React, Next.js, Angular, Node.js, TypeScript, Python, "
            "FastAPI, Django, PostgreSQL, MongoDB, and Docker with a strong dedication to clean code and automated testing."
        ),
        "skills": [
            ("Frontend Development", "React.js, Next.js, Angular, TypeScript, JavaScript (ES6+), HTML5, CSS3/SASS, Tailwind CSS, Responsive Design, State Management."),
            ("Backend Architecture", "Node.js, Express.js, Python, FastAPI, Django, RESTful APIs, GraphQL, gRPC, Webhooks, WebSockets."),
            ("Databases & Caching", "PostgreSQL, MySQL, MongoDB, Redis (Redlock), BullMQ, Schema Modeling, Query Optimization."),
            ("DevOps, Cloud & QA", "Docker, Kubernetes (K3s), AWS (EC2, S3), Azure, Git/GitHub Actions (CI/CD), Jest (200+ Tests), pytest, Linux/Unix."),
        ],
        "experience": [
            {
                "title": "Freelance Full Stack Software Engineer",
                "right": "Oct 2025 – Present (1 Year)",
                "sub": "Independent Software Contractor, Egypt",
                "sub_right": "",
                "bullets": [
                    "Built full-stack business management portals with Angular/React frontends and Node.js/PostgreSQL backends.",
                    "Implemented secure authentication, role-based access control (RBAC), and responsive UI layouts for business workflows.",
                    "Integrated Paymob payment processing, automated email notifications, and webhook handlers for real-time status updates.",
                    "Refactored frontend components into modular templates, accelerating feature delivery and improving rendering speed.",
                ],
            },
            {
                "title": "Open Source Core Contributor — Cantera Scientific Engine",
                "right": "Active Contributor",
                "sub": "Python, C++, Linux Environments, CI/CD Automated Pipelines",
                "sub_right": '<a href="https://github.com/Cantera/cantera/pulls?q=author:hazalkoom">Pull Requests</a>',
                "bullets": [
                    "Contributed core bug fixes and maintenance to an enterprise-grade scientific computing library on GitHub.",
                    "Resolved memory leaks, execution bugs, and toolchain failures across GitHub Actions CI/CD matrix build pipelines.",
                ],
            },
            {
                "title": "Software Engineering Trainee — NTI Immersive Program",
                "right": "Jun 2025 – Oct 2025 (4 Months)",
                "sub": "National Telecommunication Institute (NTI), Egypt",
                "sub_right": "",
                "bullets": [
                    "Completed a 210-hour intensive track in full-stack web development, API testing, and relational database systems.",
                    "Collaborated with peer engineers to build modular full-stack applications with React, Node.js, Express, and PostgreSQL.",
                ],
            },
        ],
        "projects": [
            {
                "title": "SmartCart Full-Stack E-Commerce Platform",
                "right": '<a href="https://github.com/hazalkoom/smartCart">Source Code</a>',
                "sub": "TypeScript, React/Next.js, Node.js, Express.js, PostgreSQL, MongoDB, Redis, Docker, Paymob",
                "bullets": [
                    "Built an end-to-end e-commerce platform with dynamic UI views and 50+ RESTful APIs supporting checkout and payments.",
                    "Configured asynchronous task queues using BullMQ/Redis and maintained 200+ unit tests with Jest for system reliability.",
                ],
            },
            {
                "title": "AeroLock — Real-Time Distributed Services Engine",
                "right": '<a href="https://github.com/hazalkoom/AeroLock">Source Code</a>',
                "sub": "Python, FastAPI, gRPC, PostgreSQL, Redis Redlock, WebSockets, Azure, K3s",
                "bullets": [
                    "Developed asynchronous microservices with Python and Node.js, implementing Redis distributed locking for concurrency control.",
                ],
            },
            {
                "title": "RealEstate Engine — Modular Backend Monolith",
                "right": '<a href="https://github.com/hazalkoom/real-estate-platform">Source Code</a>',
                "sub": "Python, Django, PostgreSQL, GraphQL, pytest, Qdrant Vector DB",
                "bullets": [
                    "Built a property marketplace backend with Qdrant vector search and eliminated N+1 queries using GraphQL DataLoaders.",
                ],
            },
        ],
    },

    "Mohamed_Ahmed-Frontend.pdf": {
        "role": "Frontend Software Engineer",
        "profile": (
            "Frontend Software Engineer with 1.5+ years of combined experience crafting responsive, high-performance web applications "
            "and Single Page Applications (SPAs). Specialized in React.js, Next.js, Angular, TypeScript, Tailwind CSS, REST/GraphQL "
            "integrations, and automated UI testing with Jest. Dedicated to clean component design, cross-browser compatibility, and seamless UX."
        ),
        "skills": [
            ("Frontend Technologies", "React.js, Next.js, Angular, TypeScript, JavaScript (ES6+), HTML5, CSS3/SASS, Tailwind CSS, Responsive Design, State Management, Webpack/Vite."),
            ("API Integration & Web", "RESTful APIs, GraphQL, WebSockets, Webhooks, JSON, Client-Side Caching, Cross-Browser Compatibility."),
            ("Testing & Performance", "Jest (200+ Automated Unit/Integration Tests), UI Regression Testing, Chrome DevTools, Lighthouse Optimization."),
            ("Backend & Cloud Basics", "Node.js, Express.js, PostgreSQL, Docker, Git/GitHub Actions (CI/CD), Linux/Unix, Vercel Deployment."),
        ],
        "experience": [
            {
                "title": "Freelance Frontend & Web Developer",
                "right": "Oct 2025 – Present (1 Year)",
                "sub": "Independent Software Contractor, Egypt",
                "sub_right": "",
                "bullets": [
                    "Developed dynamic, interactive web portals and client dashboards using React, Next.js, and Angular with Tailwind CSS.",
                    "Integrated frontend interfaces with RESTful APIs, handling asynchronous data fetching, form validation, and error states.",
                    "Implemented responsive, mobile-first layouts ensuring pixel-perfect rendering across modern desktop and mobile browsers.",
                    "Refactored monolithic UI codebases into modular, reusable component libraries, accelerating sprint velocity by 30%.",
                ],
            },
            {
                "title": "Open Source Contributor — Cantera Scientific Engine",
                "right": "Active Contributor",
                "sub": "Python, C++, Automated Testing, Linux, GitHub Actions CI/CD",
                "sub_right": '<a href="https://github.com/Cantera/cantera/pulls?q=author:hazalkoom">Pull Requests</a>',
                "bullets": [
                    "Diagnosed and resolved runtime defects, ensuring cross-platform stability across automated CI/CD matrix build pipelines.",
                ],
            },
            {
                "title": "Software Engineering Trainee — NTI Immersive Program",
                "right": "Jun 2025 – Oct 2025 (4 Months)",
                "sub": "National Telecommunication Institute (NTI), Egypt",
                "sub_right": "",
                "bullets": [
                    "Completed a 210-hour intensive track focused on modern frontend engineering, component lifecycle, and state management.",
                    "Collaborated with cross-functional developers in Agile sprints to build dynamic web application modules with React and Node.js.",
                ],
            },
        ],
        "projects": [
            {
                "title": "SmartCart Full-Stack E-Commerce Platform",
                "right": '<a href="https://github.com/hazalkoom/smartCart">Source Code</a>',
                "sub": "TypeScript, React/Next.js, Tailwind CSS, Node.js, Express.js, PostgreSQL, Jest (200+ Tests)",
                "bullets": [
                    "Built an interactive e-commerce SPA with dynamic product filtering, cart state management, and Paymob checkout integration.",
                    "Maintained 200+ automated Jest tests covering core UI workflows and API integration logic.",
                ],
            },
            {
                "title": "RealEstate Engine — Property Marketplace Web Platform",
                "right": '<a href="https://github.com/hazalkoom/real-estate-platform">Source Code</a>',
                "sub": "TypeScript, React, GraphQL, Tailwind CSS, Python/Django, PostgreSQL",
                "bullets": [
                    "Designed dynamic property discovery interfaces with real-time filtering, GraphQL queries, and responsive card layouts.",
                ],
            },
            {
                "title": "AeroLock — Real-Time Monitoring Web Dashboard",
                "right": '<a href="https://github.com/hazalkoom/AeroLock">Source Code</a>',
                "sub": "TypeScript, WebSockets, React, Tailwind CSS, FastAPI, Redis",
                "bullets": [
                    "Created real-time event monitoring dashboards utilizing WebSockets for live status feeds and distributed concurrency updates.",
                ],
            },
        ],
    },

    "Mohamed_Ahmed-QA_Testing.pdf": {
        "role": "Junior QA & Software Testing Engineer",
        "profile": (
            "Detail-oriented Junior QA & Software Testing Engineer with 1.5+ years of combined experience in automated "
            "unit/integration testing, API validation, root-cause bug analysis, and full-stack software development. "
            "Experienced in writing 200+ automated tests using Jest and pytest, validating REST/GraphQL APIs, debugging "
            "CI/CD pipelines in GitHub Actions, and ensuring defect-free releases across web and backend systems."
        ),
        "skills": [
            ("Testing & QA Automation", "Jest (200+ Unit/Integration Tests), pytest, Playwright, API Testing (Postman/REST/GraphQL), Regression Testing, Bug Triage & Root-Cause Analysis, Test Case Design, TDD."),
            ("Languages & Scripting", "Python, JavaScript (ES6+), TypeScript, SQL, Bash, C++, HTML5/CSS3."),
            ("Backend & Web Systems", "Node.js, Express.js, FastAPI, Django, React.js, Angular, Webhooks, Payment Gateway Validation."),
            ("Databases & Data Integrity", "PostgreSQL, MySQL, MongoDB, Redis, Schema Validation, Query Verification."),
            ("CI/CD, DevOps & Tools", "Git/GitHub Actions (Automated Test Matrices), Docker, Linux/Unix, Issue Tracking, Agile/Scrum."),
        ],
        "experience": [
            {
                "title": "Freelance Full Stack & QA Software Engineer",
                "right": "Oct 2025 – Present (1 Year)",
                "sub": "Independent Software Contractor, Egypt",
                "sub_right": "",
                "bullets": [
                    "Designed and executed comprehensive test suites (unit, integration, and end-to-end API validation) for client web applications and RESTful services.",
                    "Validated third-party payment gateway workflows (Paymob/Fawry), webhook idempotency, and role-based access control (RBAC) edge cases.",
                    "Performed cross-browser UI testing and regression checks on Angular and React portals, documenting and resolving defects prior to deployment.",
                    "Verified PostgreSQL and MongoDB data integrity, input sanitization, and error-handling behavior under concurrent user loads.",
                ],
            },
            {
                "title": "Open Source Core Contributor — Cantera Scientific Engine",
                "right": "Active Contributor",
                "sub": "Python, C++, Automated Testing, Linux, GitHub Actions CI/CD",
                "sub_right": '<a href="https://github.com/Cantera/cantera/pulls?q=author:hazalkoom">Pull Requests</a>',
                "bullets": [
                    "Conducted root-cause analysis and debugging on complex scientific computing defects, authoring regression tests for merged fixes.",
                    "Diagnosed and resolved memory leaks, runtime crashes, and cross-platform CI/CD test matrix failures in GitHub Actions.",
                ],
            },
            {
                "title": "Software Engineering Trainee — NTI Immersive Program",
                "right": "Jun 2025 – Oct 2025 (4 Months)",
                "sub": "National Telecommunication Institute (NTI), Egypt",
                "sub_right": "",
                "bullets": [
                    "Completed a 210-hour intensive software engineering program covering full-stack development, API testing, and relational database verification.",
                    "Collaborated in Agile sprints conducting peer code reviews, defect reproduction, and functional verification of web modules.",
                ],
            },
        ],
        "projects": [
            {
                "title": "SmartCart Full-Stack E-Commerce Platform — 200+ Automated Tests",
                "right": '<a href="https://github.com/hazalkoom/smartCart">Source Code</a>',
                "sub": "TypeScript, Jest (200+ Tests), Node.js, Express.js, React/Next.js, PostgreSQL, Redis, Docker",
                "bullets": [
                    "Engineered an automated testing suite of 200+ Jest unit and integration tests validating checkout, inventory, authentication, and payment APIs.",
                    "Verified asynchronous BullMQ/Redis job queues and webhook retry mechanisms to prevent duplicate order processing.",
                ],
            },
            {
                "title": "RealEstate Engine — Modular Backend & pytest Validation Suite",
                "right": '<a href="https://github.com/hazalkoom/real-estate-platform">Source Code</a>',
                "sub": "Python, Django, pytest, PostgreSQL, GraphQL, Qdrant Vector DB",
                "bullets": [
                    "Built automated pytest test suites verifying domain logic, relational constraints, and GraphQL DataLoader query performance.",
                    "Benchmarked and eliminated N+1 query bottlenecks while validating vector search accuracy.",
                ],
            },
            {
                "title": "AeroLock — Real-Time Distributed Services Engine",
                "right": '<a href="https://github.com/hazalkoom/AeroLock">Source Code</a>',
                "sub": "Python, FastAPI, gRPC, PostgreSQL, Redis Redlock, WebSockets, K3s",
                "bullets": [
                    "Tested distributed locking concurrency controls and WebSocket/gRPC service reliability under concurrent request scenarios.",
                ],
            },
        ],
    },

    "Mohamed_Ahmed-Application_Support.pdf": {
        "role": "Application Support & Technical Support Engineer",
        "profile": (
            "Application Support & Software Engineer with 1.5+ years of combined experience troubleshooting, deploying, "
            "and maintaining web applications, REST APIs, and SQL/NoSQL databases. Skilled in diagnosing production issues, "
            "analyzing logs, debugging API/webhook integrations, writing SQL queries, and communicating clear resolutions to technical and non-technical stakeholders."
        ),
        "skills": [
            ("Application Support & Troubleshooting", "Incident Diagnosis, Root-Cause Analysis (RCA), Log Analysis, API & Webhook Debugging, Bug Reproduction, Technical Documentation, Client Support."),
            ("Languages & Databases", "SQL (PostgreSQL, MySQL), Python, JavaScript/TypeScript, Bash, MongoDB, Redis, Query Optimization & Data Fixes."),
            ("APIs & Web Technologies", "RESTful APIs, GraphQL, Webhooks, Payment Gateways (Paymob/Fawry), Node.js, Express.js, FastAPI, Django, React, Angular, HTML5/CSS3."),
            ("Systems, Cloud & DevOps", "Linux/Unix Administration, Docker, Kubernetes (K3s), AWS (EC2), Azure, Git/GitHub Actions (CI/CD), Jest, pytest."),
        ],
        "experience": [
            {
                "title": "Freelance Full Stack & Application Support Engineer",
                "right": "Oct 2025 – Present (1 Year)",
                "sub": "Independent Software Contractor, Egypt",
                "sub_right": "",
                "bullets": [
                    "Provided end-to-end production application support, troubleshooting, and maintenance for client-facing portals and e-commerce platforms.",
                    "Investigated and resolved payment gateway failures (Paymob/Fawry), webhook delivery errors, and REST API integration issues.",
                    "Executed SQL queries on PostgreSQL/MySQL databases to audit transaction records, resolve data discrepancies, and optimize slow reports.",
                    "Communicated directly with clients to gather issue details, reproduce bugs, deploy hotfixes, and document operational workflows.",
                ],
            },
            {
                "title": "Open Source Core Contributor — Cantera Scientific Engine",
                "right": "Active Contributor",
                "sub": "Python, C++, Linux Environments, Debugging & Issue Resolution",
                "sub_right": '<a href="https://github.com/Cantera/cantera/pulls?q=author:hazalkoom">Pull Requests</a>',
                "bullets": [
                    "Triaged user-reported issues, reproduced runtime crashes on Linux environments, and delivered verified bug fixes in Python and C++.",
                    "Diagnosed build and deployment failures across multi-OS GitHub Actions CI/CD pipelines.",
                ],
            },
            {
                "title": "Software Engineering Trainee — NTI Immersive Program",
                "right": "Jun 2025 – Oct 2025 (4 Months)",
                "sub": "National Telecommunication Institute (NTI), Egypt",
                "sub_right": "",
                "bullets": [
                    "Completed a 210-hour intensive track in full-stack web architecture, relational database administration, and API troubleshooting.",
                    "Collaborated with cross-functional peers to debug full-stack React, Node.js, and PostgreSQL applications.",
                ],
            },
        ],
        "projects": [
            {
                "title": "SmartCart Full-Stack E-Commerce & Payment Platform",
                "right": '<a href="https://github.com/hazalkoom/smartCart">Source Code</a>',
                "sub": "TypeScript, Node.js, Express.js, React, PostgreSQL, Redis, Docker, Paymob, Jest (200+ Tests)",
                "bullets": [
                    "Built and supported 50+ REST API endpoints handling checkout, order lifecycle, webhook callbacks, and RBAC permissions.",
                    "Implemented structured error logging, BullMQ task retry queues, and 200+ automated tests to ensure high service availability.",
                ],
            },
            {
                "title": "AeroLock — Real-Time Distributed Services Engine",
                "right": '<a href="https://github.com/hazalkoom/AeroLock">Source Code</a>',
                "sub": "Python, FastAPI, gRPC, PostgreSQL, Redis Redlock, WebSockets, Azure, K3s",
                "bullets": [
                    "Deployed containerized microservices on Linux/K3s and Azure with health checks, concurrency locking, and real-time monitoring.",
                ],
            },
            {
                "title": "RealEstate Engine — Modular Backend Monolith",
                "right": '<a href="https://github.com/hazalkoom/real-estate-platform">Source Code</a>',
                "sub": "Python, Django, PostgreSQL, GraphQL, pytest, Qdrant Vector DB",
                "bullets": [
                    "Maintained relational database integrity and resolved GraphQL N+1 query performance bottlenecks.",
                ],
            },
        ],
    },

    "Mohamed_Ahmed-IT_Support.pdf": {
        "role": "IT Support & Systems Engineer",
        "profile": (
            "Technical IT Support & Systems Engineer combining formal training in Operating Systems, Computer Networking, "
            "Linux administration, and Cloud Infrastructure (AWS Certified) with strong troubleshooting and user-support skills. "
            "Experienced in diagnosing OS, network, software, and database issues, automating tasks with Python/Bash, managing "
            "Docker/Linux environments, and resolving technical service requests promptly."
        ),
        "skills": [
            ("IT Support & Systems Administration", "Linux/Unix & Windows Troubleshooting, OS Installation & Configuration, System Diagnostics, User Account & Access Management (RBAC), Incident Resolution, Remote Desktop & Ticketing Support."),
            ("Networking & Security", "TCP/IP, DNS, HTTP/HTTPS, SSH, VPN/Firewalls, Routing Fundamentals, JWT/OAuth2 Authentication, Data Backup & Recovery."),
            ("Cloud, Virtualization & DevOps", "AWS (Certified Cloud Practitioner, EC2), Microsoft Azure, Docker Containers, Kubernetes (K3s), Git/GitHub Actions."),
            ("Scripting, Databases & Tools", "Bash Scripting, Python Automation, SQL (PostgreSQL, MySQL), HTML/CSS/JS, Microsoft Office (Excel, Word), Hardware & Software Diagnostics."),
        ],
        "experience": [
            {
                "title": "Technical Systems & Full Stack Contractor",
                "right": "Oct 2025 – Present (1 Year)",
                "sub": "Independent Technical Contractor, Egypt",
                "sub_right": "",
                "bullets": [
                    "Configured, deployed, and maintained Linux servers, Docker containers, and cloud-hosted web applications for business clients.",
                    "Administered role-based access control (RBAC), user accounts, database backups, and SSL/HTTPS network configurations.",
                    "Provided direct technical support to end users, diagnosing software errors, connectivity issues, and workstation/browser problems.",
                    "Automated routine system maintenance, data backups, and log checks using Python and Bash scripts.",
                ],
            },
            {
                "title": "Open Source Contributor — Linux & CI/CD Infrastructure (Cantera)",
                "right": "Active Contributor",
                "sub": "Linux Environments, Python, C++, Build Toolchains, GitHub Actions",
                "sub_right": '<a href="https://github.com/Cantera/cantera/pulls?q=author:hazalkoom">Pull Requests</a>',
                "bullets": [
                    "Troubleshot multi-platform Linux/macOS/Windows build environments, package dependencies, and automated CI pipeline failures.",
                    "Resolved system-level memory management and runtime configuration defects.",
                ],
            },
            {
                "title": "IT & Software Engineering Trainee — NTI Program",
                "right": "Jun 2025 – Oct 2025 (4 Months)",
                "sub": "National Telecommunication Institute (NTI), Egypt",
                "sub_right": "",
                "bullets": [
                    "Completed intensive technical training at Egypt's National Telecommunication Institute covering networking, servers, and database systems.",
                    "Assisted peers in configuring local development environments, database servers, and network services.",
                ],
            },
        ],
        "projects": [
            {
                "title": "SmartCart Infrastructure & Web Architecture",
                "right": '<a href="https://github.com/hazalkoom/smartCart">Source Code</a>',
                "sub": "Docker Containers, Linux Environment, PostgreSQL, Redis, Node.js",
                "bullets": [
                    "Configured Dockerized multi-container environments with isolated networking, persistent volumes, and health-check monitoring.",
                    "Automated local developer environment provisioning and integration test runs with Jest.",
                ],
            },
            {
                "title": "AeroLock — Distributed Services Engine & K3s Deployment",
                "right": '<a href="https://github.com/hazalkoom/AeroLock">Source Code</a>',
                "sub": "Linux/K3s, Python, Docker, Redis Redlock, WebSockets, Azure Cloud",
                "bullets": [
                    "Maintained service availability and verified distributed lock timeouts under multi-client network partition scenarios.",
                ],
            },
            {
                "title": "RealEstate Engine — Database & Infrastructure Operations",
                "right": '<a href="https://github.com/hazalkoom/real-estate-platform">Source Code</a>',
                "sub": "PostgreSQL Administration, Docker, Linux, Python/Django, Qdrant",
                "bullets": [
                    "Managed PostgreSQL schema migrations, indexes, and database connection pooling to ensure high query performance.",
                ],
            },
        ],
    },
}


def render_html(spec: dict) -> str:
    skills_html = "\n".join(
        f"<p><strong>{cat}:</strong> {items}</p>" for cat, items in spec["skills"]
    )
    exp_html = ""
    for e in spec["experience"]:
        bullets = "\n".join(f"<li>{b}</li>" for b in e["bullets"])
        sub_right = f"<span>{e['sub_right']}</span>" if e.get("sub_right") else ""
        exp_html += f"""
        <div class="entry">
            <div class="entry-header">
                <span>{e['title']}</span>
                <span class="right">{e['right']}</span>
            </div>
            <div class="entry-sub">
                <span>{e['sub']}</span>
                {sub_right}
            </div>
            <ul>{bullets}</ul>
        </div>
        """
    proj_html = ""
    for p in spec["projects"]:
        bullets = "\n".join(f"<li>{b}</li>" for b in p["bullets"])
        proj_html += f"""
        <div class="entry">
            <div class="entry-header">
                <span>{p['title']}</span>
                <span class="right">{p['right']}</span>
            </div>
            <div class="entry-sub">
                <span>{p['sub']}</span>
            </div>
            <ul>{bullets}</ul>
        </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>{BASE_CSS}</style>
</head>
<body>
    <div class="header">
        <h1>Mohamed Ahmed</h1>
        <div class="subtitle">{spec['role']}</div>
        <div class="contact">
            <a href="mailto:hazalkoom048@gmail.com">hazalkoom048@gmail.com</a> — +20 109 078 4033 — Cairo, Egypt<br>
            <a href="https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/">linkedin.com/in/mohamed-ahmed-mahmoud</a> — <a href="https://github.com/hazalkoom">github.com/hazalkoom</a>
        </div>
    </div>

    <div class="section">
        <div class="section-title">Profile</div>
        <p>{spec['profile']}</p>
    </div>

    <div class="section">
        <div class="section-title">Technical Skills</div>
        <div class="skills-list">
            {skills_html}
        </div>
    </div>

    <div class="section">
        <div class="section-title">Experience</div>
        {exp_html}
    </div>

    <div class="section">
        <div class="section-title">Projects</div>
        {proj_html}
    </div>

    <div class="section">
        <div class="section-title">Education & Certifications</div>
        <div class="edu-row">
            <strong>Diploma in Software Engineering (Computer Science)</strong>
            <span>Sep 2025 – Jun 2026</span>
        </div>
        <p style="margin-bottom: 2px;">EPIC Institute of Technology — <em>Real-Time Systems, Advanced Algorithms, Data Structures, Computer Networking.</em></p>
        <div class="edu-row">
            <strong>Bachelor of Tourism and Hospitality</strong>
            <span>Oct 2022 – Nov 2026 (Graduated)</span>
        </div>
        <p style="margin-bottom: 2px;">Mansoura University, Egypt — <em>Grade: Good</em></p>
        <p style="margin-top: 2px;">
            <strong>Certifications:</strong>
            <a href="https://www.credly.com/badges/2f608a67-3e4a-4547-8db9-18883eaed2c7/linked_in_profile">AWS Certified Cloud Practitioner</a> —
            <a href="https://www.coursera.org/account/accomplishments/specialization/Z0VTOYO96MLF">Advanced Django Specialization</a> —
            <a href="https://www.coursera.org/account/accomplishments/verify/SBL9VFEJGO3A">Advanced Docker</a> —
            <a href="https://www.freecodecamp.org/certification/fcc84eac740-6721-40ae-b329-7d1f700c3bbf/javascript-algorithms-and-data-structures">freeCodeCamp JS Algorithms</a>
        </p>
    </div>
</body>
</html>
"""


def main():
    CVS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for filename, spec in CVS_SPEC.items():
            out_path = CVS_DIR / filename
            html = render_html(spec)
            page.set_content(html, wait_until="load")
            page.pdf(path=str(out_path), format="A4", print_background=True)
            info = subprocess.check_output(["pdfinfo", str(out_path)], text=True)
            pages = [line for line in info.splitlines() if "Pages:" in line][0]
            print(f"Generated {out_path.name} -> {pages.strip()}")
        browser.close()


if __name__ == "__main__":
    main()
