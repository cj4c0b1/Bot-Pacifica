"""
Launcher for Pacifica Cockpit Dashboard
"""

import subprocess
import sys
import os

def check_requirements():
    """Check if required packages are installed"""
    required_packages = [
        'streamlit',
        'plotly',
        'pandas',
        'numpy',
        'redis'
    ]

    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)

    if missing_packages:
        print(f"Installing missing packages: {', '.join(missing_packages)}")
        for package in missing_packages:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])

    # Also install project-specific modules if available
    try:
        import src.redis_client
        import src.performance_tracker
        import src.position_manager
        print("✅ Project modules found")
    except ImportError as e:
        print(f"⚠️  Some project modules not found: {e}")
        print("Dashboard will use mock data for demonstration")

def run_dashboard():
    """Run the Pacifica Cockpit dashboard"""
    print("🚀 Starting Pacifica Cockpit...")
    print("Dashboard will be available at: http://localhost:8501")
    print("Press Ctrl+C to stop")

    # Run streamlit
    subprocess.call([
        sys.executable, '-m', 'streamlit', 'run',
        'pacifica_cockpit.py',
        '--server.port', '8501',
        '--server.address', '0.0.0.0'
    ])

if __name__ == "__main__":
    check_requirements()
    run_dashboard()
