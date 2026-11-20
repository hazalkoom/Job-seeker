#!/usr/bin/env python3
"""Generate role-tailored 1-page CVs in cvs/ modeled on Mohamed_Ahmed-general2.pdf.

Uses verified experience, projects (with GitHub links), open-source Cantera PRs,
and verified certificates with clickable verification links.
"""

from __future__ import annotations

import html
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CVS_DIR = ROOT / "cvs"
BASE_CV = ROOT / "Mohamed_Ahmed-general2.pdf"

CONTACT_EMAIL = "hazalkoom048@gmail.com"
CONTACT_PHONE = "+20 109 078 4033"
PORTFOLIO_URL = "https://mohamed-ahmed-five.vercel.app/"
LINKEDIN_URL = "https://www.linkedin.com/in/mohamed-ahmed-mahmoud-766912268/"
GITHUB_URL = "https://github.com/hazalkoom"
CANTERA_PRS_URL = "https://github.com/Cantera/cantera/pulls?q=author:hazalkoom"

CERT_LINKS: dict[str, str] = {
    "AWS Certified Cloud Practitioner": "https://aws.amazon.com/verification",
    "Advanced Django Specialization (Mastering Django & DRF)": "https://coursera.org/verify/specialization/Z0VTOYO96MLF",
    "Advanced Django Specialization": "https://coursera.org/verify/specialization/Z0VTOYO96MLF",
    "Advanced Django & DRF": "https://coursera.org/verify/6OLQGGYOKUMV",
    "Advanced Django: External APIs & Task Queuing": "https://coursera.org/verify/4XLHSNYYRK1H",
    "Ultimate TypeScript Course 2024": "https://coursera.org/verify/KQC3WQ9P0V3O",
    "Intermediate PostgreSQL": "https://coursera.org/verify/NDP4E3GWILDN",
    "Database Design & Basic SQL in PostgreSQL": "https://coursera.org/verify/VCDHSLE3PKDA",
    "Database Design & SQL in PostgreSQL": "https://coursera.org/verify/VCDHSLE3PKDA",
    "SQL for Data Science": "https://coursera.org/verify/FJET95DJ997X",
    "Advanced Docker: Data Persistence & Orchestration": "https://coursera.org/verify/SBL9VFEJGO3A",
    "Advanced Docker": "https://coursera.org/verify/SBL9VFEJGO3A",
    "Docker Fundamentals": "https://coursera.org/verify/B01WTHXIOJM1",
    "Kubernetes Essentials": "https://coursera.org/verify/AGVUPLCLJNEI",
    "Hands-on Linux Commands & Shell Scripting": "https://coursera.org/verify/A6J321H09ZYM",
    "Hands-on Linux & Shell Scripting": "https://coursera.org/verify/A6J321H09ZYM",
    "Foundations of Coding Full-Stack": "https://coursera.org/verify/5YKP8I7JBR9S",
    "Introduction to Web Development": "https://coursera.org/verify/72AJB1KHROUP",
    "Generative AI Essentials": "https://coursera.org/verify/QSXM1S4YNW82",
    "Learn Claude Code": "https://coursera.org/verify/YLYLPAWHAL4B",
    "Learn Cursor AI": "https://coursera.org/verify/Y1HALJAU255Y",
    "Learn GitHub Copilot": "https://coursera.org/verify/WW5K9HK4XU5D",
    "Graph Theory": "https://coursera.org/verify/RRE6JSBR6OXS",
    "Introduction to Programming With C#": "https://coursera.org/verify/XI7JH1BBEO08",
    "freeCodeCamp JS Algorithms": "https://www.freecodecamp.org/",
}

# Reusable verified experience entries
EXP_FREELANCE_FS = {
    "title": "Freelance Full Stack Software Engineer",
    "date": "Oct 2025 – Present",
    "org": "Independent Software Contractor",
    "loc": "Cairo, Egypt",
    "bullets": [
        "Developed custom internal management portals using Angular and React with role-based access control (RBAC) for client workflows.",
        "Architected RESTful backend services and database schemas using Node.js and PostgreSQL to manage inventory and user CRUD operations.",
        "Integrated third-party payment gateways (Paymob/Fawry) and webhooks to automate order status updates and transactional communication.",
        "Refactored legacy frontend codebases into modular, reusable component templates, improving load speed and UI responsiveness.",
    ],
}

EXP_FREELANCE_BE = {
    "title": "Freelance Backend Software Engineer",
    "date": "Oct 2025 – Present",
    "org": "Independent Software Contractor",
    "loc": "Cairo, Egypt",
    "bullets": [
        "Architected RESTful backend APIs and normalized PostgreSQL schemas using Node.js, Express, and Python to power client inventory and user workflows.",
        "Integrated third-party payment gateways (Paymob/Fawry) and webhook handlers to automate order status updates and transactional notifications.",
        "Implemented role-based access control (RBAC), request validation, and query optimizations to keep API responses fast and reliable.",
    ],
}

EXP_FREELANCE_FE = {
    "title": "Freelance Frontend & Full Stack Engineer",
    "date": "Oct 2025 – Present",
    "org": "Independent Software Contractor",
    "loc": "Cairo, Egypt",
    "bullets": [
        "Built responsive client management portals using Angular, React, TypeScript, and Tailwind CSS with role-based access control (RBAC).",
        "Refactored legacy frontend codebases into modular, reusable component templates, improving load speed and UI responsiveness.",
        "Connected frontend applications to Node.js/PostgreSQL REST APIs and payment gateway webhooks (Paymob/Fawry).",
    ],
}

EXP_FREELANCE_SUPPORT = {
    "title": "Freelance Software & Technical Support Engineer",
    "date": "Oct 2025 – Present",
    "org": "Independent Software Contractor",
    "loc": "Cairo, Egypt",
    "bullets": [
        "Diagnosed and resolved production API, database, and webhook integration issues (Paymob/Fawry) for client web applications.",
        "Managed PostgreSQL schemas, SQL troubleshooting queries, and role-based access control (RBAC) portals for business operations.",
        "Maintained Linux deployment environments, Docker containers, and automated monitoring scripts to keep client services stable.",
    ],
}

EXP_CANTERA = {
    "title": "Open Source Core Contributor — Cantera Scientific Engine",
    "date": "Active Contributor",
    "org": "Python, C++, Linux Environments, CI/CD Automated Pipelines",
    "loc": "GitHub",
    "url": CANTERA_PRS_URL,
    "url_label": "Merged PRs",
    "bullets": [
        "Contributed core bug fixes and maintenance to an enterprise-grade scientific computing library on GitHub.",
        "Resolved memory leaks, execution bugs, and compiler toolchain failures across GitHub Actions CI/CD matrix build pipelines.",
    ],
}

EXP_NTI = {
    "title": "Software Engineering Trainee — NTI Immersive Program",
    "date": "Jun 2025 – Oct 2025",
    "org": "National Telecommunication Institute (NTI)",
    "loc": "Mansoura, Egypt",
    "bullets": [
        "Completed a 210-hour on-site software engineering track focused on full-stack web development and database management.",
        "Partnered with peer developers to build web application modules using React, Node.js, Express, and PostgreSQL in Agile sprints.",
    ],
}

# Reusable verified project entries
PROJ_SMARTCART = {
    "name": "SmartCart Full-Stack E-Commerce Platform",
    "stack": "TypeScript, React/Next.js, Node.js, Express, PostgreSQL, Redis, Paymob",
    "url": "https://github.com/hazalkoom/smartCart",
    "bullets": [
        "Built an end-to-end e-commerce platform with dynamic frontends and RESTful API endpoints supporting checkout and payment processing.",
        "Configured asynchronous task queues using BullMQ/Redis and maintained 200+ unit tests with Jest to ensure system reliability.",
    ],
}

PROJ_AEROLOCK = {
    "name": "AeroLock — Real-Time Distributed Services Engine",
    "stack": "Python, FastAPI, gRPC, PostgreSQL, Redis, K3s, Azure",
    "url": "https://github.com/hazalkoom/AeroLock",
    "bullets": [
        "Developed asynchronous microservices with Python and Node.js, implementing Redis distributed locking (Redlock) for concurrency control.",
    ],
}

PROJ_REALESTATE = {
    "name": "RealEstate Engine — Modular Backend Monolith",
    "stack": "Python, Django, PostgreSQL, GraphQL, pytest, Qdrant",
    "url": "https://github.com/hazalkoom/real-estate-platform",
    "bullets": [
        "Developed a property marketplace backend enforcing relational integrity and leveraging Qdrant vector search capabilities.",
        "Eliminated N+1 query execution bottlenecks using GraphQL DataLoaders and validated core domain logic with pytest.",
    ],
}

PROJ_JOBHUNTER = {
    "name": "Job Hunter — Autonomous Job Discovery & Application Platform",
    "stack": "Python, FastAPI, Playwright, SQLite, GitHub Actions, Telegram API, pytest",
    "url": "https://github.com/hazalkoom/Job-seeker",
    "bullets": [
        "Built an end-to-end automated job aggregation, calibrated scoring, and Playwright ATS form-filling platform with 220+ automated pytest tests.",
        "Implemented Gmail IMAP inbox reconciliation, multi-ATS adapters (Greenhouse, Ashby, Workable, Lever), and scheduled GitHub Actions CI/CD runs.",
    ],
}


CV_SPECS: list[dict] = [
    {
        "filename": "Mohamed_Ahmed-Software_Engineer.pdf",
        "subtitle": "Software Engineer (Full Stack & Backend Systems)",
        "profile": (
            "Software Engineer with 1.5+ years of combined experience in freelance software development, open-source engineering (Cantera), "
            "and immersive training. Proficient in Python, TypeScript, Node.js, Angular, React, PostgreSQL, Docker, and automated testing."
        ),
        "skills": [
            ("Languages & Frameworks", "Python, TypeScript, JavaScript (ES6+), Node.js, Express, FastAPI, Django, Angular, React.js, Next.js"),
            ("Databases & Messaging", "PostgreSQL, MySQL, MongoDB, SQLite, Redis (Redlock), BullMQ, Qdrant, GraphQL, gRPC, RESTful APIs"),
            ("DevOps, Cloud & QA", "Docker, Kubernetes (K3s), AWS (EC2), Azure, Linux/Unix, Git/GitHub Actions (CI/CD), pytest, Jest, Playwright"),
        ],
        "experience": [EXP_FREELANCE_FS, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_SMARTCART, PROJ_JOBHUNTER, PROJ_AEROLOCK],
        "certs": [
            "AWS Certified Cloud Practitioner",
            "Foundations of Coding Full-Stack",
            "Ultimate TypeScript Course 2024",
            "Intermediate PostgreSQL",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Junior_Software_Engineer.pdf",
        "subtitle": "Junior Software Engineer (Python / TypeScript / Full Stack)",
        "profile": (
            "Junior Software Engineer with 1.5+ years of hands-on experience building production web portals, REST/GraphQL APIs, "
            "and automated test suites. Active open-source contributor to Cantera with strong foundations in Linux, Docker, and PostgreSQL."
        ),
        "skills": [
            ("Backend & APIs", "Python, FastAPI, Django, Node.js, Express.js, TypeScript, JavaScript (ES6+), RESTful APIs, GraphQL, Webhooks"),
            ("Frontend & UI", "Angular, React.js, Next.js, HTML5, CSS3/SASS, Tailwind CSS, RBAC Portals, Component Templates"),
            ("Databases & DevOps", "PostgreSQL, MySQL, SQLite, MongoDB, Redis, Docker, Kubernetes (K3s), Linux/Unix, GitHub Actions, pytest, Jest"),
        ],
        "experience": [EXP_FREELANCE_FS, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_JOBHUNTER, PROJ_SMARTCART, PROJ_REALESTATE],
        "certs": [
            "Foundations of Coding Full-Stack",
            "AWS Certified Cloud Practitioner",
            "Advanced Django Specialization",
            "Advanced Docker",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Software_Developer.pdf",
        "subtitle": "Software Developer (Web Applications & APIs)",
        "profile": (
            "Software Developer with 1.5+ years of combined experience delivering full-stack web applications, payment gateway integrations, "
            "and database-backed services in TypeScript, Node.js, and Python."
        ),
        "skills": [
            ("Web & Backend", "TypeScript, JavaScript (ES6+), Node.js, Express.js, Python, Django, FastAPI, RESTful APIs, GraphQL, Webhooks"),
            ("Frontend", "Angular, React.js, Next.js, HTML5, CSS3/SASS, Tailwind CSS, State Management, Responsive Design"),
            ("Data, Cloud & QA", "PostgreSQL, MySQL, MongoDB, Redis, Docker, Linux/Unix, AWS (EC2), Azure, GitHub Actions, Jest, pytest"),
        ],
        "experience": [EXP_FREELANCE_FS, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_SMARTCART, PROJ_REALESTATE, PROJ_JOBHUNTER],
        "certs": [
            "Ultimate TypeScript Course 2024",
            "Foundations of Coding Full-Stack",
            "Database Design & Basic SQL in PostgreSQL",
            "freeCodeCamp JS Algorithms",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Backend_NodeJS.pdf",
        "subtitle": "Backend Software Engineer (Node.js / TypeScript)",
        "profile": (
            "Backend Software Engineer with 1.5+ years of combined experience in freelance backend development, open-source engineering, "
            "and immersive software training. Specialized in Node.js, Express.js, TypeScript, PostgreSQL, Redis, and scalable REST/GraphQL APIs."
        ),
        "skills": [
            ("Backend & APIs", "Node.js, Express.js, NestJS, TypeScript, JavaScript (ES6+), RESTful APIs, GraphQL, gRPC, Webhooks, Payment Gateways"),
            ("Databases & Messaging", "PostgreSQL, MySQL, MongoDB, Redis (Redlock), BullMQ, Schema Modeling, Query Optimization, Transactions"),
            ("Secondary Backend", "Python, FastAPI, Django, C++, C, SQL, Bash, Operating Systems, Computer Networking"),
            ("DevOps, Cloud & Testing", "Docker, Kubernetes (K3s), AWS (EC2), Azure, Linux/Unix, Git/GitHub Actions (CI/CD), Jest, pytest, Playwright"),
        ],
        "experience": [EXP_FREELANCE_BE, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_SMARTCART, PROJ_AEROLOCK, PROJ_REALESTATE],
        "certs": [
            "Ultimate TypeScript Course 2024",
            "Intermediate PostgreSQL",
            "Advanced Docker: Data Persistence & Orchestration",
            "freeCodeCamp JS Algorithms",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Backend_Python.pdf",
        "subtitle": "Backend Software Engineer (Python / Django / FastAPI)",
        "profile": (
            "Backend Software Engineer with 1.5+ years of combined experience building Python APIs, distributed services, and automated "
            "workflows. Skilled in Python, Django, Django REST Framework, FastAPI, PostgreSQL, Redis, GraphQL, and pytest."
        ),
        "skills": [
            ("Python & Backend", "Python, Django, Django REST Framework, FastAPI, RESTful APIs, GraphQL, gRPC, Webhooks, AsyncIO, Task Queues"),
            ("Databases & Search", "PostgreSQL, SQLite, MySQL, MongoDB, Redis (Redlock), Qdrant Vector DB, Schema Modeling, Query Optimization"),
            ("Secondary Languages", "TypeScript, JavaScript (ES6+), Node.js, Express.js, C++, C, SQL, Bash"),
            ("DevOps, Cloud & QA", "Docker, Kubernetes (K3s), AWS (EC2), Azure, Linux/Unix, Git/GitHub Actions (CI/CD), pytest, Playwright"),
        ],
        "experience": [EXP_FREELANCE_BE, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_REALESTATE, PROJ_AEROLOCK, PROJ_JOBHUNTER],
        "certs": [
            "Advanced Django Specialization (Mastering Django & DRF)",
            "Intermediate PostgreSQL",
            "Advanced Docker",
            "AWS Certified Cloud Practitioner",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Backend_Django.pdf",
        "subtitle": "Python & Django Backend Developer",
        "profile": (
            "Python & Django Developer with hands-on experience building modular monoliths, Django REST Framework APIs, GraphQL schemas, "
            "and asynchronous task queues backed by PostgreSQL and Redis."
        ),
        "skills": [
            ("Django & Python", "Python, Django, Django REST Framework (DRF), GraphQL, DataLoaders, Celery/Task Queuing, External APIs, pytest"),
            ("Databases & Search", "PostgreSQL, SQLite, MySQL, Redis, Qdrant Vector DB, Relational Modeling, N+1 Query Optimization"),
            ("Web & Integrations", "Node.js, TypeScript, RESTful APIs, Webhooks, Paymob/Fawry Payment Integrations, RBAC Authentication"),
            ("Infrastructure", "Docker, Kubernetes (K3s), Linux/Unix, AWS (EC2), Azure, Git/GitHub Actions (CI/CD)"),
        ],
        "experience": [EXP_FREELANCE_BE, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_REALESTATE, PROJ_JOBHUNTER, PROJ_AEROLOCK],
        "certs": [
            "Advanced Django Specialization (Mastering Django & DRF)",
            "Advanced Django & DRF",
            "Advanced Django: External APIs & Task Queuing",
            "Intermediate PostgreSQL",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Backend_FastAPI.pdf",
        "subtitle": "Python & FastAPI Backend Developer",
        "profile": (
            "Python & FastAPI Developer experienced in building asynchronous microservices, gRPC interfaces, distributed locking with Redis, "
            "and automated Playwright/API workflows deployed on Docker and Kubernetes (K3s)."
        ),
        "skills": [
            ("FastAPI & Async", "Python, FastAPI, AsyncIO, gRPC, RESTful APIs, Webhooks, Playwright Automation, Pydantic, pytest"),
            ("Distributed Systems", "Redis (Redlock), BullMQ, PostgreSQL, SQLite, MongoDB, Qdrant Vector DB, Concurrency Control"),
            ("Secondary Stack", "Node.js, Express.js, TypeScript, Django, C++, C, Bash"),
            ("Containers & Cloud", "Docker, Kubernetes (K3s), Linux/Unix, AWS (EC2), Azure, GitHub Actions (CI/CD)"),
        ],
        "experience": [EXP_FREELANCE_BE, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_AEROLOCK, PROJ_JOBHUNTER, PROJ_REALESTATE],
        "certs": [
            "AWS Certified Cloud Practitioner",
            "Kubernetes Essentials",
            "Advanced Docker: Data Persistence & Orchestration",
            "Intermediate PostgreSQL",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Backend_General.pdf",
        "subtitle": "Backend Software Engineer (Node.js & Python)",
        "profile": (
            "Backend Software Engineer with 1.5+ years of combined experience in freelance API architecture, open-source engineering, and "
            "intensive software training. Proficient in Node.js, Express, TypeScript, Python, Django, FastAPI, PostgreSQL, Redis, and Docker."
        ),
        "skills": [
            ("Backend & APIs", "Node.js, Express.js, Python, FastAPI, Django, RESTful APIs, GraphQL, gRPC, Webhooks, Third-Party Integrations"),
            ("Databases & Messaging", "PostgreSQL, MySQL, MongoDB, Redis (Redlock), BullMQ, Qdrant, Schema Modeling, Query Optimization"),
            ("Languages & Core", "TypeScript, JavaScript (ES6+), Python, C++, C, SQL, Bash, Operating Systems, Computer Networking"),
            ("DevOps, Cloud & Testing", "Docker, Kubernetes (K3s), AWS (EC2), Azure, Linux/Unix, Git/GitHub Actions (CI/CD), Jest, pytest"),
        ],
        "experience": [EXP_FREELANCE_BE, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_SMARTCART, PROJ_AEROLOCK, PROJ_REALESTATE],
        "certs": [
            "AWS Certified Cloud Practitioner",
            "Advanced Django Specialization",
            "Intermediate PostgreSQL",
            "Advanced Docker",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-API_Engineer.pdf",
        "subtitle": "API & Backend Integrations Engineer",
        "profile": (
            "Backend & API Engineer experienced in designing RESTful, GraphQL, and gRPC services, payment gateway webhooks (Paymob/Fawry), "
            "RBAC authorization, and automated API testing using Python, Node.js, and PostgreSQL."
        ),
        "skills": [
            ("API Architecture", "RESTful APIs, GraphQL (DataLoaders), gRPC, Webhooks, Payment Gateways (Paymob/Fawry), RBAC, Request Validation"),
            ("Backend Languages", "Node.js, Express.js, TypeScript, Python, FastAPI, Django, Django REST Framework"),
            ("Data & Queues", "PostgreSQL, MySQL, MongoDB, Redis (Redlock), BullMQ, SQL Query Optimization"),
            ("DevOps & Testing", "Docker, Kubernetes (K3s), Linux/Unix, AWS (EC2), GitHub Actions (CI/CD), pytest, Jest, Playwright"),
        ],
        "experience": [EXP_FREELANCE_BE, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_SMARTCART, PROJ_REALESTATE, PROJ_JOBHUNTER],
        "certs": [
            "Advanced Django: External APIs & Task Queuing",
            "Ultimate TypeScript Course 2024",
            "Intermediate PostgreSQL",
            "Advanced Docker",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-FullStack_Angular.pdf",
        "subtitle": "Full Stack Software Engineer (Angular & Node.js / Python)",
        "profile": (
            "Full Stack Software Engineer with 1.5+ years of combined experience building enterprise web portals and scalable APIs. "
            "Skilled in Angular, TypeScript, Node.js, Express, Python, PostgreSQL, and modular component architecture."
        ),
        "skills": [
            ("Frontend Architecture", "Angular, TypeScript, JavaScript (ES6+), HTML5, CSS3/SASS, Tailwind CSS, RxJS, RBAC Portals, Component Templates, React.js"),
            ("Backend & APIs", "Node.js, Express.js, Python, FastAPI, Django, RESTful APIs, GraphQL, gRPC, Webhooks, Paymob/Fawry Integrations"),
            ("Databases & Messaging", "PostgreSQL, MySQL, MongoDB, Redis (Redlock), BullMQ, Schema Modeling, Query Optimization"),
            ("DevOps, Cloud & QA", "Docker, Kubernetes (K3s), AWS (EC2), Azure, Linux/Unix, Git/GitHub Actions (CI/CD), Jest, pytest"),
        ],
        "experience": [EXP_FREELANCE_FS, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_SMARTCART, PROJ_REALESTATE, PROJ_AEROLOCK],
        "certs": [
            "Ultimate TypeScript Course 2024",
            "Foundations of Coding Full-Stack",
            "Intermediate PostgreSQL",
            "freeCodeCamp JS Algorithms",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-FullStack_React.pdf",
        "subtitle": "Full Stack Software Engineer (React / Next.js & Node.js)",
        "profile": (
            "Full Stack Software Engineer with 1.5+ years of combined experience delivering responsive web applications and RESTful backends. "
            "Skilled in React.js, Next.js, TypeScript, Node.js, Express, PostgreSQL, Redis, and Tailwind CSS."
        ),
        "skills": [
            ("Frontend Architecture", "React.js, Next.js, TypeScript, JavaScript (ES6+), Angular, HTML5, CSS3/SASS, Tailwind CSS, State Management"),
            ("Backend & APIs", "Node.js, Express.js, Python, FastAPI, Django, RESTful APIs, GraphQL, Webhooks, Third-Party Payment Integrations"),
            ("Databases & Messaging", "PostgreSQL, MySQL, MongoDB, Redis (Redlock), BullMQ, Schema Modeling, Query Optimization"),
            ("DevOps, Cloud & QA", "Docker, Kubernetes (K3s), AWS (EC2), Azure, Linux/Unix, Git/GitHub Actions (CI/CD), Jest, pytest"),
        ],
        "experience": [EXP_FREELANCE_FS, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_SMARTCART, PROJ_AEROLOCK, PROJ_REALESTATE],
        "certs": [
            "Ultimate TypeScript Course 2024",
            "Foundations of Coding Full-Stack",
            "Introduction to Web Development",
            "freeCodeCamp JS Algorithms",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-FullStack_Python.pdf",
        "subtitle": "Full Stack Software Engineer (Python / Django / FastAPI & TypeScript)",
        "profile": (
            "Full Stack Software Engineer with 1.5+ years of combined experience building Python-powered web platforms and modern TypeScript "
            "frontends. Skilled in Python, Django, FastAPI, Angular, React, PostgreSQL, Docker, and automated testing."
        ),
        "skills": [
            ("Backend & Python", "Python, Django, Django REST Framework, FastAPI, Node.js, Express.js, RESTful APIs, GraphQL, gRPC, Webhooks"),
            ("Frontend Architecture", "TypeScript, JavaScript (ES6+), Angular, React.js, Next.js, HTML5, CSS3/SASS, Tailwind CSS, State Management"),
            ("Databases & Messaging", "PostgreSQL, SQLite, MySQL, MongoDB, Redis (Redlock), Qdrant, Schema Modeling, Query Optimization"),
            ("DevOps, Cloud & QA", "Docker, Kubernetes (K3s), AWS (EC2), Azure, Linux/Unix, Git/GitHub Actions (CI/CD), pytest, Jest, Playwright"),
        ],
        "experience": [EXP_FREELANCE_FS, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_REALESTATE, PROJ_JOBHUNTER, PROJ_SMARTCART],
        "certs": [
            "Advanced Django Specialization",
            "Foundations of Coding Full-Stack",
            "Intermediate PostgreSQL",
            "Advanced Docker",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-FullStack_TypeScript.pdf",
        "subtitle": "Full Stack TypeScript Developer (Node.js / React / Angular)",
        "profile": (
            "Full Stack TypeScript Developer with 1.5+ years of experience building type-safe client portals and backend APIs with TypeScript, "
            "Node.js, Express, React/Next.js, Angular, PostgreSQL, Redis, and Jest."
        ),
        "skills": [
            ("TypeScript & Full Stack", "TypeScript, JavaScript (ES6+), Node.js, Express.js, React.js, Next.js, Angular, HTML5, CSS3/SASS, Tailwind CSS"),
            ("APIs & Databases", "RESTful APIs, GraphQL, gRPC, Webhooks, PostgreSQL, MySQL, MongoDB, Redis (Redlock), BullMQ"),
            ("Secondary & DevOps", "Python, FastAPI, Django, Docker, Kubernetes (K3s), Linux/Unix, GitHub Actions (CI/CD), Jest, Playwright"),
        ],
        "experience": [EXP_FREELANCE_FS, EXP_NTI, EXP_CANTERA],
        "projects": [PROJ_SMARTCART, PROJ_AEROLOCK, PROJ_REALESTATE],
        "certs": [
            "Ultimate TypeScript Course 2024",
            "Foundations of Coding Full-Stack",
            "freeCodeCamp JS Algorithms",
            "Intermediate PostgreSQL",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Frontend.pdf",
        "subtitle": "Frontend Software Engineer (Angular / React / TypeScript)",
        "profile": (
            "Frontend Software Engineer with 1.5+ years of combined experience building responsive, component-driven web interfaces and "
            "enterprise management portals. Skilled in TypeScript, Angular, React.js, Next.js, HTML5, CSS3/SASS, and Tailwind CSS."
        ),
        "skills": [
            ("Frontend Architecture", "TypeScript, JavaScript (ES6+), Angular, React.js, Next.js, HTML5, CSS3/SASS, Tailwind CSS, Component Templates, State Management"),
            ("UI Engineering & Testing", "Responsive Design, RBAC Dashboards, REST/GraphQL Integration, Jest, Playwright E2E Testing, Performance Refactoring"),
            ("Backend Familiarity", "Node.js, Express.js, Python, FastAPI, PostgreSQL, RESTful APIs, Webhooks"),
            ("Tooling & Workflow", "Git, GitHub Actions (CI/CD), Docker, Linux/Unix, Agile Sprints"),
        ],
        "experience": [EXP_FREELANCE_FE, EXP_NTI, EXP_CANTERA],
        "projects": [PROJ_SMARTCART, PROJ_REALESTATE, PROJ_JOBHUNTER],
        "certs": [
            "Ultimate TypeScript Course 2024",
            "Introduction to Web Development",
            "freeCodeCamp JS Algorithms",
            "Foundations of Coding Full-Stack",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-React_Developer.pdf",
        "subtitle": "React / Next.js Frontend Developer",
        "profile": (
            "React & TypeScript Frontend Developer with hands-on experience building modular web interfaces, e-commerce storefronts, and "
            "RBAC dashboards backed by REST and GraphQL APIs."
        ),
        "skills": [
            ("React & TypeScript", "React.js, Next.js, TypeScript, JavaScript (ES6+), HTML5, CSS3/SASS, Tailwind CSS, State Management, Reusable Components"),
            ("Testing & APIs", "Jest (200+ unit tests), Playwright E2E Testing, RESTful APIs, GraphQL, Node.js, Express.js"),
            ("Tooling & Collaboration", "Git, GitHub Actions (CI/CD), Docker, Linux/Unix, Angular, Agile Sprints"),
        ],
        "experience": [EXP_FREELANCE_FE, EXP_NTI, EXP_CANTERA],
        "projects": [PROJ_SMARTCART, PROJ_JOBHUNTER, PROJ_REALESTATE],
        "certs": [
            "Ultimate TypeScript Course 2024",
            "Introduction to Web Development",
            "freeCodeCamp JS Algorithms",
            "Foundations of Coding Full-Stack",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Angular_Developer.pdf",
        "subtitle": "Angular & TypeScript Frontend Developer",
        "profile": (
            "Angular & TypeScript Frontend Developer experienced in building internal management portals with role-based access control (RBAC), "
            "modular component templates, and RESTful backend integrations."
        ),
        "skills": [
            ("Angular & TypeScript", "Angular, TypeScript, JavaScript (ES6+), RxJS, HTML5, CSS3/SASS, Tailwind CSS, RBAC Portals, Component Refactoring"),
            ("Backend & APIs", "Node.js, Express.js, Python, FastAPI, PostgreSQL, RESTful APIs, Payment Gateway Webhooks"),
            ("Testing & Tooling", "Jest, Playwright, Git, GitHub Actions (CI/CD), Docker, Linux/Unix, React.js"),
        ],
        "experience": [EXP_FREELANCE_FE, EXP_NTI, EXP_CANTERA],
        "projects": [PROJ_SMARTCART, PROJ_REALESTATE, PROJ_JOBHUNTER],
        "certs": [
            "Ultimate TypeScript Course 2024",
            "Foundations of Coding Full-Stack",
            "Introduction to Web Development",
            "freeCodeCamp JS Algorithms",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Web_Developer.pdf",
        "subtitle": "Web Developer (JavaScript / TypeScript / Full Stack)",
        "profile": (
            "Web Developer with 1.5+ years of experience designing responsive frontends and scalable backend APIs. Skilled in JavaScript, "
            "TypeScript, React, Angular, Node.js, Python, PostgreSQL, and third-party payment integrations."
        ),
        "skills": [
            ("Web Frontend", "HTML5, CSS3/SASS, Tailwind CSS, JavaScript (ES6+), TypeScript, React.js, Next.js, Angular, Responsive UI"),
            ("Web Backend", "Node.js, Express.js, Python, Django, FastAPI, RESTful APIs, GraphQL, Webhooks (Paymob/Fawry)"),
            ("Databases & DevOps", "PostgreSQL, MySQL, MongoDB, Redis, Docker, Git, GitHub Actions (CI/CD), Jest, Playwright"),
        ],
        "experience": [EXP_FREELANCE_FS, EXP_NTI, EXP_CANTERA],
        "projects": [PROJ_SMARTCART, PROJ_REALESTATE, PROJ_JOBHUNTER],
        "certs": [
            "Introduction to Web Development",
            "Foundations of Coding Full-Stack",
            "Ultimate TypeScript Course 2024",
            "freeCodeCamp JS Algorithms",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-AI_Applications.pdf",
        "subtitle": "AI Application & Software Engineer (Python / LLMs / APIs)",
        "profile": (
            "Software Engineer with 1.5+ years of experience building Python/TypeScript backend systems, vector-search applications, and "
            "automated AI-assisted workflows. Skilled in Python, FastAPI, Django, Qdrant, Node.js, PostgreSQL, and modern AI coding workflows."
        ),
        "skills": [
            ("AI & Automation", "Generative AI Applications, Vector Search (Qdrant), Automated Scoring & Classification Pipelines, Claude Code, Cursor AI, GitHub Copilot"),
            ("Backend & APIs", "Python, FastAPI, Django, Node.js, Express.js, TypeScript, RESTful APIs, GraphQL, gRPC, Webhooks, Playwright"),
            ("Databases & Queues", "PostgreSQL, SQLite, Redis (Redlock), BullMQ, MongoDB, Schema Modeling, Query Optimization"),
            ("DevOps, Cloud & QA", "Docker, Kubernetes (K3s), AWS (EC2), Azure, Linux/Unix, GitHub Actions (CI/CD), pytest, Jest"),
        ],
        "experience": [EXP_FREELANCE_FS, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_JOBHUNTER, PROJ_REALESTATE, PROJ_AEROLOCK],
        "certs": [
            "Generative AI Essentials",
            "Learn Claude Code",
            "Learn Cursor AI",
            "Learn GitHub Copilot",
            "AWS Certified Cloud Practitioner",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Workflow_Automation.pdf",
        "subtitle": "Workflow Automation & Integrations Engineer",
        "profile": (
            "Software & Automation Engineer with 1.5+ years of experience building end-to-end API integrations, webhook pipelines, browser "
            "automation, and scheduled task workflows using Python, Node.js, Playwright, Redis/BullMQ, and GitHub Actions."
        ),
        "skills": [
            ("Automation & Integrations", "Playwright Browser Automation, Webhooks, Third-Party APIs (Paymob/Fawry, Telegram, Gmail IMAP), BullMQ, Redis Queues, GitHub Actions"),
            ("Languages & Backend", "Python, FastAPI, Django, Node.js, Express.js, TypeScript, JavaScript (ES6+), Bash Scripting, RESTful APIs, GraphQL"),
            ("Databases & Systems", "PostgreSQL, SQLite, MongoDB, Redis, Schema Modeling, Query Optimization, Docker, Kubernetes (K3s), Linux/Unix"),
            ("Testing & Cloud", "pytest, Jest, AWS (EC2), Azure, CI/CD Scheduled Pipelines"),
        ],
        "experience": [EXP_FREELANCE_BE, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_JOBHUNTER, PROJ_SMARTCART, PROJ_AEROLOCK],
        "certs": [
            "Advanced Django: External APIs & Task Queuing",
            "Generative AI Essentials",
            "Hands-on Linux & Shell Scripting",
            "Advanced Docker",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-QA_Automation.pdf",
        "subtitle": "QA & Test Automation Engineer (SDET)",
        "profile": (
            "Software & QA Automation Engineer with 1.5+ years of experience building automated E2E, integration, and unit test suites "
            "across Python and TypeScript applications. Skilled in Playwright, pytest, Jest, API testing, CI/CD pipelines, and bug triage."
        ),
        "skills": [
            ("Test Automation & QA", "Playwright (E2E & Browser Automation), pytest, Jest, API Testing, Regression Testing, Test Cases, CI/CD Matrix Testing"),
            ("Languages & Frameworks", "Python, TypeScript, JavaScript (ES6+), SQL, Bash, C++, Node.js, Express, FastAPI, Django, Angular, React"),
            ("Databases & Systems", "PostgreSQL, SQLite, MySQL, Redis, Linux/Unix, Docker, Git/GitHub Actions, Memory Leak & Build Debugging"),
        ],
        "experience": [EXP_CANTERA, EXP_FREELANCE_FS, EXP_NTI],
        "projects": [PROJ_JOBHUNTER, PROJ_SMARTCART, PROJ_REALESTATE],
        "certs": [
            "Advanced Docker",
            "Hands-on Linux Commands & Shell Scripting",
            "Ultimate TypeScript Course 2024",
            "Database Design & SQL in PostgreSQL",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-QA_Engineer.pdf",
        "subtitle": "QA Engineer (Web, API & Automated Testing)",
        "profile": (
            "QA Engineer with 1+ years of practical testing and software engineering experience writing automated E2E browser tests (Playwright), "
            "unit/integration suites (pytest, Jest), and debugging CI/CD failures."
        ),
        "skills": [
            ("Testing & QA", "Playwright, pytest, Jest, Automated Regression Testing, API & Webhook Testing, Bug Triage, CI/CD Matrix Verification"),
            ("Languages & Web", "Python, JavaScript (ES6+), TypeScript, SQL, Bash, HTML5, CSS3, RESTful APIs, GraphQL"),
            ("Infrastructure", "Docker, Linux/Unix, Git/GitHub Actions, PostgreSQL, SQLite, Redis"),
        ],
        "experience": [EXP_CANTERA, EXP_FREELANCE_SUPPORT, EXP_NTI],
        "projects": [PROJ_JOBHUNTER, PROJ_SMARTCART, PROJ_REALESTATE],
        "certs": [
            "Hands-on Linux Commands & Shell Scripting",
            "Database Design & Basic SQL in PostgreSQL",
            "Ultimate TypeScript Course 2024",
            "Advanced Docker",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Linux_OpenSource.pdf",
        "subtitle": "Software Engineer (Linux, Python & C++ / Open Source)",
        "profile": (
            "Software Engineer and Open Source Core Contributor with 1.5+ years of experience in Linux environments, Python, C++, CI/CD "
            "build pipelines, and distributed backend systems. Experienced in debugging memory leaks, compiler toolchains, and container deployments."
        ),
        "skills": [
            ("Systems & Languages", "Python, C++, C, Bash/Shell Scripting, Linux/Unix (Ubuntu/Debian), Operating Systems, Computer Networking, SQL"),
            ("DevOps & Containers", "Docker, Kubernetes (K3s), Git/GitHub Actions (CI/CD Matrix Builds), AWS (EC2), Azure, Automated Testing (pytest)"),
            ("Backend & Databases", "FastAPI, Django, Node.js, TypeScript, gRPC, RESTful APIs, PostgreSQL, Redis (Redlock), SQLite"),
        ],
        "experience": [EXP_CANTERA, EXP_FREELANCE_BE, EXP_NTI],
        "projects": [PROJ_AEROLOCK, PROJ_JOBHUNTER, PROJ_REALESTATE],
        "certs": [
            "Hands-on Linux Commands & Shell Scripting",
            "Advanced Docker: Data Persistence & Orchestration",
            "Kubernetes Essentials",
            "Graph Theory",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Linux_Systems_Engineer.pdf",
        "subtitle": "Junior Linux & Systems Engineer",
        "profile": (
            "Junior Linux & Systems Engineer with 2 years of daily Linux experience (Ubuntu/Debian), Bash scripting, Docker containerization, "
            "C++/Python toolchain debugging, and Kubernetes (K3s) deployments."
        ),
        "skills": [
            ("Linux & Systems", "Linux/Unix (Ubuntu/Debian), Bash/Shell Scripting, Operating Systems, Computer Networking, Process & Environment Management"),
            ("Containers & Cloud", "Docker, Docker Compose, Kubernetes (K3s), AWS (EC2), Azure, GitHub Actions (CI/CD Matrix Builds)"),
            ("Programming & DBs", "Python, C++, C, SQL, FastAPI, PostgreSQL, SQLite, Redis"),
        ],
        "experience": [EXP_CANTERA, EXP_FREELANCE_SUPPORT, EXP_NTI],
        "projects": [PROJ_AEROLOCK, PROJ_JOBHUNTER, PROJ_SMARTCART],
        "certs": [
            "Hands-on Linux Commands & Shell Scripting",
            "Advanced Docker: Data Persistence & Orchestration",
            "Kubernetes Essentials",
            "AWS Certified Cloud Practitioner",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Cloud_DevOps.pdf",
        "subtitle": "Junior Cloud & DevOps Engineer",
        "profile": (
            "Cloud-focused Software Engineer with 1.5+ years of experience deploying containerized microservices, CI/CD pipelines, and "
            "scalable APIs on Linux, Docker, Kubernetes (K3s), AWS, and Azure. AWS Certified Cloud Practitioner."
        ),
        "skills": [
            ("Cloud & Orchestration", "AWS (EC2), Azure, Docker, Docker Compose, Kubernetes (K3s), Linux/Unix, Bash Scripting, GitHub Actions (CI/CD)"),
            ("Backend & Services", "Python, FastAPI, Django, Node.js, Express.js, TypeScript, gRPC, RESTful APIs, Webhooks"),
            ("Databases & Messaging", "PostgreSQL, Redis (Redlock), BullMQ, MySQL, MongoDB, SQLite, Schema Modeling, Query Optimization"),
            ("Testing & Reliability", "pytest, Jest, Playwright, CI/CD Matrix Builds, Concurrency Control, Automated Monitoring"),
        ],
        "experience": [EXP_CANTERA, EXP_FREELANCE_BE, EXP_NTI],
        "projects": [PROJ_AEROLOCK, PROJ_JOBHUNTER, PROJ_SMARTCART],
        "certs": [
            "AWS Certified Cloud Practitioner",
            "Kubernetes Essentials",
            "Advanced Docker: Data Persistence & Orchestration",
            "Hands-on Linux & Shell Scripting",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Database_API.pdf",
        "subtitle": "Backend & PostgreSQL Database Developer",
        "profile": (
            "Backend Software Engineer with 1.5+ years of experience designing relational and NoSQL database schemas, eliminating N+1 query "
            "bottlenecks, and building high-reliability REST, GraphQL, and gRPC APIs in Python and Node.js."
        ),
        "skills": [
            ("Databases & Optimization", "PostgreSQL, MySQL, SQLite, MongoDB, Redis (Redlock), Qdrant, Schema Modeling, Query Optimization, GraphQL DataLoaders"),
            ("Backend & APIs", "Python, Django, FastAPI, Node.js, Express.js, TypeScript, RESTful APIs, GraphQL, gRPC, BullMQ, Webhooks"),
            ("DevOps & Testing", "Docker, Kubernetes (K3s), Linux/Unix, AWS (EC2), Azure, GitHub Actions (CI/CD), pytest, Jest"),
        ],
        "experience": [EXP_FREELANCE_BE, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_REALESTATE, PROJ_AEROLOCK, PROJ_SMARTCART],
        "certs": [
            "Intermediate PostgreSQL",
            "Database Design & Basic SQL in PostgreSQL",
            "SQL for Data Science",
            "Advanced Django Specialization",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Application_Support.pdf",
        "subtitle": "Application & Technical Support Engineer (APIs / SQL / Linux)",
        "profile": (
            "Technical & Application Support Engineer with 1.5+ years of hands-on software engineering experience diagnosing production APIs, "
            "PostgreSQL databases, webhook integrations, and Linux environments. Skilled in SQL, Python, Node.js, Docker, and customer-facing troubleshooting."
        ),
        "skills": [
            ("Support & Diagnostics", "Application Support, API & Webhook Troubleshooting, SQL Diagnostics, Log Analysis, RBAC Administration, Incident Resolution"),
            ("Systems & Cloud", "Linux/Unix, Bash Scripting, Docker, AWS (EC2), Azure, Computer Networking, Git/GitHub Actions"),
            ("Development & Databases", "PostgreSQL, MySQL, MongoDB, Redis, Python, FastAPI, Django, Node.js, TypeScript, RESTful APIs, Playwright, pytest"),
        ],
        "experience": [EXP_FREELANCE_SUPPORT, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_SMARTCART, PROJ_JOBHUNTER, PROJ_REALESTATE],
        "certs": [
            "AWS Certified Cloud Practitioner",
            "Hands-on Linux Commands & Shell Scripting",
            "Database Design & Basic SQL in PostgreSQL",
            "Docker Fundamentals",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-Developer_Support.pdf",
        "subtitle": "Developer Support Engineer (APIs / SDKs / Debugging)",
        "profile": (
            "Developer Support Engineer with software engineering background in Python, TypeScript, Node.js, REST/GraphQL APIs, and webhooks. "
            "Experienced in diagnosing integration failures, reproducing bugs, debugging CI/CD builds, and writing clear technical solutions."
        ),
        "skills": [
            ("Developer Support", "API & Webhook Integration Debugging, SDK/Code Reproduction, Bug Triage, Root-Cause Analysis, Technical Documentation"),
            ("Languages & APIs", "Python, TypeScript, JavaScript (ES6+), Node.js, Express, FastAPI, Django, RESTful APIs, GraphQL, gRPC"),
            ("Systems & Databases", "PostgreSQL, SQLite, Redis, Docker, Linux/Unix, Git/GitHub Actions, pytest, Jest, Playwright"),
        ],
        "experience": [EXP_FREELANCE_SUPPORT, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_JOBHUNTER, PROJ_SMARTCART, PROJ_AEROLOCK],
        "certs": [
            "AWS Certified Cloud Practitioner",
            "Advanced Django: External APIs & Task Queuing",
            "Ultimate TypeScript Course 2024",
            "Hands-on Linux Commands & Shell Scripting",
        ],
    },
    {
        "filename": "Mohamed_Ahmed-IT_Support.pdf",
        "subtitle": "IT & Systems Support Specialist",
        "profile": (
            "IT & Systems Support Specialist with 1.5+ years of practical experience in Linux/Unix administration, computer networking, "
            "SQL database troubleshooting, RBAC user management, and Bash/Python automation. AWS Certified Cloud Practitioner."
        ),
        "skills": [
            ("IT & Systems Support", "Linux/Unix (Ubuntu/Debian), Windows, Computer Networking, Bash/Shell Scripting, RBAC User Management, System Troubleshooting"),
            ("Cloud & Containers", "AWS (EC2), Azure, Docker, Virtual Machines, Git/GitHub Actions, Automated Monitoring & Reporting"),
            ("Databases & Scripting", "PostgreSQL, MySQL, SQLite, SQL Queries, Python, JavaScript, RESTful APIs, Webhook Diagnostics"),
        ],
        "experience": [EXP_FREELANCE_SUPPORT, EXP_CANTERA, EXP_NTI],
        "projects": [PROJ_JOBHUNTER, PROJ_SMARTCART, PROJ_AEROLOCK],
        "certs": [
            "Hands-on Linux Commands & Shell Scripting",
            "AWS Certified Cloud Practitioner",
            "Docker Fundamentals",
            "Database Design & Basic SQL in PostgreSQL",
        ],
    },
]


def _render_certs_html(certs: list[str] | str) -> str:
    esc = html.escape
    if isinstance(certs, str):
        items = [c.strip() for c in certs.split("|") if c.strip()]
    else:
        items = list(certs)
    rendered = []
    for cert in items:
        url = CERT_LINKS.get(cert)
        if url:
            rendered.append(f'<a class="cert-link" href="{esc(url)}">{esc(cert)}</a>')
        else:
            rendered.append(esc(cert))
    return " <span class=\"sep\">|</span> ".join(rendered)


def _render_html(spec: dict) -> str:
    esc = html.escape

    skills_html = "\n".join(
        f'<div class="skill-row"><strong>{esc(cat)}:</strong> {esc(vals)}</div>'
        for cat, vals in spec["skills"]
    )

    exp_blocks = []
    for exp in spec["experience"]:
        bullets = "\n".join(f"<li>{esc(b)}</li>" for b in exp["bullets"])
        title_html = esc(exp["title"])
        if exp.get("url"):
            label = esc(exp.get("url_label") or "Link")
            title_html = f'{title_html} <span class="proj-sep">|</span> <a class="repo-link" href="{esc(exp["url"])}">{label}</a>'
        exp_blocks.append(
            f"""
            <div class="entry">
              <div class="entry-head">
                <span class="entry-title">{title_html}</span>
                <span class="entry-date">{esc(exp['date'])}</span>
              </div>
              <div class="entry-sub">
                <span class="entry-org">{esc(exp['org'])}</span>
                <span class="entry-loc">{esc(exp['loc'])}</span>
              </div>
              <ul>{bullets}</ul>
            </div>
            """
        )

    proj_blocks = []
    for proj in spec["projects"]:
        bullets = "\n".join(f"<li>{esc(b)}</li>" for b in proj["bullets"])
        repo_url = proj.get("url") or GITHUB_URL
        proj_blocks.append(
            f"""
            <div class="entry">
              <div class="entry-head">
                <span><span class="entry-title">{esc(proj['name'])}</span> <span class="proj-sep">|</span> <span class="proj-stack">{esc(proj['stack'])}</span></span>
                <a class="repo-link" href="{esc(repo_url)}">GitHub Repo</a>
              </div>
              <ul>{bullets}</ul>
            </div>
            """
        )

    certs_html = _render_certs_html(spec["certs"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: letter;
    margin: 0.42in 0.5in 0.4in 0.5in;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Liberation Serif", "DejaVu Serif", "Times New Roman", Georgia, serif;
    color: #111;
    font-size: 9.6pt;
    line-height: 1.28;
  }}
  .header {{
    text-align: center;
    margin-bottom: 7pt;
  }}
  .name {{
    font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
    font-size: 20pt;
    font-weight: 700;
    letter-spacing: 0.2pt;
    margin-bottom: 1.5pt;
  }}
  .subtitle {{
    font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
    font-size: 10.5pt;
    font-weight: 700;
    color: #1a1a1a;
    margin-bottom: 2pt;
  }}
  .loc-line {{
    font-size: 9.2pt;
    color: #222;
    margin-bottom: 2.5pt;
  }}
  .contact {{
    font-size: 9pt;
    color: #111;
  }}
  .contact a {{
    color: #111;
    text-decoration: none;
  }}
  .sep {{
    margin: 0 4pt;
    color: #555;
  }}
  h2 {{
    font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
    font-size: 10.6pt;
    font-weight: 700;
    border-bottom: 0.9pt solid #222;
    padding-bottom: 1.5pt;
    margin-top: 7pt;
    margin-bottom: 4pt;
    color: #000;
  }}
  .profile-text {{
    font-size: 9.4pt;
    line-height: 1.3;
  }}
  .skill-row {{
    font-size: 9.2pt;
    margin-bottom: 1.5pt;
    line-height: 1.26;
  }}
  .entry {{
    margin-bottom: 5pt;
  }}
  .entry-head {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8pt;
  }}
  .entry-title {{
    font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
    font-weight: 700;
    font-size: 9.6pt;
  }}
  .entry-date {{
    font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
    font-weight: 700;
    font-size: 9pt;
    white-space: nowrap;
  }}
  .entry-sub {{
    display: flex;
    justify-content: space-between;
    font-style: italic;
    font-size: 9.1pt;
    color: #222;
    margin-bottom: 1.5pt;
  }}
  .proj-sep {{ color: #555; margin: 0 2pt; }}
  .proj-stack {{ font-style: italic; font-size: 9pt; color: #222; }}
  .repo-link {{
    font-family: "Liberation Sans", "DejaVu Sans", Arial, sans-serif;
    font-weight: 700;
    font-size: 8.8pt;
    color: #111;
    text-decoration: underline;
    white-space: nowrap;
  }}
  .cert-link {{
    color: #111;
    text-decoration: underline;
  }}
  ul {{
    margin-left: 14pt;
    margin-top: 1.5pt;
  }}
  li {{
    font-size: 9.2pt;
    margin-bottom: 1.5pt;
    line-height: 1.26;
  }}
  .edu-row {{
    margin-bottom: 3pt;
  }}
  .certs {{
    font-size: 9.1pt;
    margin-top: 3pt;
    line-height: 1.28;
  }}
</style>
</head>
<body>
  <div class="header">
    <div class="name">Mohamed Ahmed</div>
    <div class="subtitle">{esc(spec['subtitle'])}</div>
    <div class="loc-line">Cairo, Egypt</div>
    <div class="contact">
      <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a>
      <span class="sep">|</span>{CONTACT_PHONE}
      <span class="sep">|</span><a href="{PORTFOLIO_URL}">Portfolio</a>
      <span class="sep">|</span><a href="{LINKEDIN_URL}">LinkedIn</a>
      <span class="sep">|</span><a href="{GITHUB_URL}">GitHub</a>
    </div>
  </div>

  <h2>Profile</h2>
  <p class="profile-text">{esc(spec['profile'])}</p>

  <h2>Technical Skills</h2>
  {skills_html}

  <h2>Experience</h2>
  {''.join(exp_blocks)}

  <h2>Projects</h2>
  {''.join(proj_blocks)}

  <h2>Education &amp; Certifications</h2>
  <div class="edu-row">
    <div class="entry-head">
      <span class="entry-title">EPIC Institute of Technology</span>
      <span class="entry-date">Sep 2025 – Jun 2026</span>
    </div>
    <div class="entry-sub">
      <span>Diploma in Software Engineering (Real-Time Systems, Algorithms, Data Structures)</span>
      <span>Cairo, Egypt</span>
    </div>
  </div>
  <div class="edu-row">
    <div class="entry-head">
      <span class="entry-title">Mansoura University</span>
      <span class="entry-date">Oct 2022 – Nov 2025</span>
    </div>
    <div class="entry-sub">
      <span>Bachelor of Tourism and Hospitality</span>
      <span>Cairo, Egypt</span>
    </div>
  </div>
  <div class="certs"><strong>Certifications:</strong> {certs_html}</div>
</body>
</html>
"""


def main() -> None:
    base_cv = BASE_CV if BASE_CV.is_file() else (ROOT / "private" / "Mohamed_Ahmed-general.pdf")
    if not base_cv.is_file():
        raise FileNotFoundError(f"Base CV not found: {BASE_CV} or {base_cv}")

    CVS_DIR.mkdir(parents=True, exist_ok=True)
    removed = 0
    for old_pdf in CVS_DIR.glob("*.pdf"):
        old_pdf.unlink()
        removed += 1
    print(f"Removed {removed} old CV PDFs from {CVS_DIR}")

    general_dest = CVS_DIR / "Mohamed_Ahmed-General.pdf"
    shutil.copy2(base_cv, general_dest)
    print(f"Copied base CV -> {general_dest.name}")

    private_dir = ROOT / "private"
    private_cv = private_dir / "Mohamed_Ahmed-general.pdf"
    if private_dir.is_dir() and base_cv.resolve() != private_cv.resolve():
        shutil.copy2(base_cv, private_cv)
        print("Updated private/Mohamed_Ahmed-general.pdf from Mohamed_Ahmed-general2.pdf")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for spec in CV_SPECS:
            html_content = _render_html(spec)
            page.set_content(html_content, wait_until="load")
            out_path = CVS_DIR / spec["filename"]
            page.pdf(
                path=str(out_path),
                format="Letter",
                print_background=True,
                prefer_css_page_size=True,
            )
            print(f"Generated {out_path.name} ({out_path.stat().st_size:,} bytes)")
        browser.close()

    print(f"Done! Total CVs in {CVS_DIR}: {len(list(CVS_DIR.glob('*.pdf')))}")


if __name__ == "__main__":
    main()
