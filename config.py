# config.py
import os
from dataclasses import dataclass, field
from typing import List

@dataclass
class Config:
    # ============================================
    # ⚠️ FILL IN YOUR REAL CREDENTIALS HERE! ⚠️
    # ============================================

    # Telegram - Get from https://my.telegram.org
    API_ID: int = 39021142  # ← Your real API ID (numbers only)
    API_HASH: str = "15fd3cf63dd9604dd70de42c83640957"  # ← Your real API hash
    PHONE: str = "+251929485742"  # ← Your real phone with country code

    # PostgreSQL
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", 5432))
    DB_NAME: str = os.getenv("DB_NAME", "ethiopian_jobs")
    DB_USER: str = os.getenv("DB_USER", "postgres")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "yourpassword")

    # ============================================================
    # AI PROVIDERS - Multi-provider fallback chain
    # ============================================================
    # Priority order: Ollama (local) -> Groq (free tier) -> Gemini
    # Set in .env: AI_PROVIDERS=ollama,groq,gemini

    # Ollama (Local - Completely Free)
    # Requires Ollama installed: https://ollama.com
    # Default model: llama3.2 (fast, good quality)
    OLLAMA_URL: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")

    # Groq (Free Tier - 1.5M tokens/day)
    # Get API key: https://console.groq.com
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    # Gemini (Google - requires API key, has rate limits)
    # Get API key: https://aistudio.google.com/app/apikey
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # Channels to monitor (we'll start with these)
    JOB_CHANNELS: List[str] = field(default_factory=lambda: [
        'ethaborede', 
        'effoyjobs',
        'jobs_in_ethiopia',
        'NGOjobsethiopia',
        'AddisjobsEthiopia',
        'EthiopianNGOjobs',
        'bankjobsethiopia',
        'ITJobsEthiopia',
        'freshersjobsethiopia',
        'kebenajobs',
    ])
    
    # Job categories with refined keywords
    CATEGORIES = {
        'it': {
            'name': 'IT & Technology',
            'icon': '💻',
            'keywords': ['developer', 'software', 'programmer', 'ict', 'computer', 
                        'cyber', 'network', 'database', 'web developer', 'mobile app',
                        'data analyst', 'system admin', 'it officer', 'it manager',
                        'frontend', 'backend', 'devops', 'cloud', 'soc analyst']
        },
        'finance': {
            'name': 'Finance & Accounting',
            'icon': '💰',
            'keywords': ['finance', 'accountant', 'audit', 'budget', 'accounting',
                        'cashier', 'financial analyst', 'bookkeeper', 'tax', 'cpa',
                        'accounts payable', 'accounts receivable', 'finance officer',
                        'financial expert', 'finance expert']
        },
        'banking': {
            'name': 'Banking & Insurance',
            'icon': '🏦',
            'keywords': ['bank ', 'banking', 'loan officer', 'credit', 'insurance',
                        'teller', 'branch manager', 'microfinance', 'ባንክ']
        },
        'admin': {
            'name': 'Administrative',
            'icon': '📋',
            'keywords': ['assistant', 'secretary', 'administrative', 'clerk', 
                        'receptionist', 'coordinator', 'executive assistant',
                        'office manager', 'admin officer', 'operation assistant']
        },
        'engineering': {
            'name': 'Engineering',
            'icon': '⚙️',
            'keywords': ['engineer', 'civil engineer', 'electrical engineer', 
                        'mechanical engineer', 'construction', 'architect', 
                        'surveyor', 'structural', 'site engineer']
        },
        'health': {
            'name': 'Healthcare',
            'icon': '🏥',
            'keywords': ['nurse', 'doctor', 'medical', 'pharmacy', 'pharmacist',
                        'hospital', 'clinical', 'lab technician', 'midwife',
                        'health officer', 'physician', 'surgeon']
        },
        'teaching': {
            'name': 'Education & Teaching',
            'icon': '📚',
            'keywords': ['teacher', 'lecturer', 'instructor', 'professor',
                        'tutor', 'trainer', 'academic', 'teaching']
        },
        'marketing': {
            'name': 'Marketing & Sales',
            'icon': '📢',
            'keywords': ['marketing', 'sales officer', 'sales manager', 'brand',
                        'digital marketing', 'social media', 'advertising', 
                        'business development', 'sales representative', 'salesman']
        },
        'ngo': {
            'name': 'NGO & Development',
            'icon': '🤝',
            'keywords': ['ngo', 'humanitarian', 'project coordinator', 'development',
                        'program officer', 'monitoring', 'evaluation', 'm&e',
                        'unicef', 'undp', 'usaid', 'who', 'ingo', 'wash']
        },
        'government': {
            'name': 'Government',
            'icon': '🏛️',
            'keywords': ['ministry', 'authority', 'government', 'public service',
                        'civil service', 'federal', 'ምርጫ ቦርድ', 'ቦርድ', 'ሚኒስቴር']
        },
        'driver': {
            'name': 'Driving & Transport',
            'icon': '🚗',
            'keywords': ['driver', 'driving', 'chauffeur', 'vehicle operator']
        },
        'logistics': {
            'name': 'Logistics & Supply Chain',
            'icon': '📦',
            'keywords': ['logistics', 'supply chain', 'warehouse', 'inventory',
                        'procurement', 'store keeper', 'dispatch', 'fleet']
        },
        'hr': {
            'name': 'Human Resources',
            'icon': '👥',
            'keywords': ['human resource', 'hr officer', 'hr manager', 'recruitment',
                        'talent', 'payroll', 'personnel', 'training officer']
        },
        'security': {
            'name': 'Security',
            'icon': '🛡️',
            'keywords': ['security guard', 'security officer', 'safety officer',
                        'security analyst', 'cyber security']
        },
        'research': {
            'name': 'Research & Analysis',
            'icon': '🔬',
            'keywords': ['researcher', 'research', 'analyst', 'data analyst',
                        'research expert', 'learning expert', 'statistician']
        },
        'fresh_graduate': {
            'name': 'Fresh Graduate / Entry Level',
            'icon': '🎓',
            'keywords': ['fresh graduate', 'junior', 'entry level', 'intern',
                        'internship', 'trainee', 'beginner']
        }
    }


config = Config()
