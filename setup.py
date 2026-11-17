from setuptools import setup, find_packages

with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

version = {}
with open('recall/version.py', encoding='utf-8') as f:
    exec(f.read(), version)

setup(
    name='recall',
    version=version['__version__'],
    description='Self-hosted shared memory server for AI coding agents (MCP + HTTP, SQLite or PostgreSQL/pgvector)',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Garrett Sheppard',
    url='https://github.com/gshepptech/recall',
    license='MIT',
    packages=find_packages(),
    package_data={'recall': ['ui.html', 'static/*']},
    python_requires='>=3.10',
    install_requires=[
        'fastapi>=0.111.0',
        'uvicorn>=0.29.0',
        'httpx>=0.27.0',
        'sqlite-vec>=0.1.1',
        'aiosqlite>=0.19.0',
        'python-dotenv>=1.0.0',
        'mcp[cli]>=1.0.0,<2',
        'starlette>=0.37.0',
    ],
    extras_require={
        'postgres': ['asyncpg>=0.29.0'],
        'dev':      ['pytest>=8', 'ruff>=0.6'],
    },
    entry_points={
        'console_scripts': [
            'recall = recall.__main__:main',
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
)
