#!/usr/bin/env python

import os
import sys


from setuptools import setup, find_packages


if sys.argv[-1] == 'publish':
    os.system('python setup.py sdist upload')
    sys.exit()

readme = open('README.rst').read()
doclink = """
Documentation
-------------

The full documentation is at http://iniesta.rtfd.org."""
history = open('HISTORY.rst').read().replace('.. :changelog:', '')

test_requires = [
    "coverage",
    'pytest',
    "pytest-cov",
    # 'pytest-asyncio',
    'pytest-redis',
    'pytest-sanic',
    'pytest-cov',
    'pytest-sugar',
    "pytest-xdist",
    "pytest-flake8",
    'boto3==1.9.99',
    'localstack==0.8.10',
    "requests",
]

version = '0.1.3.dev3'

setup(
    name='iniesta',
    version=version,
    description='Messaging integration for insanic',
    long_description=readme + '\n\n' + doclink + '\n\n' + history,
    author='Kwang Jin Kim',
    author_email='david@mymusictaste.com',
    url='https://github.com/MyMusicTate/iniesta',
    packages=find_packages(include=['iniesta',]),
    # package_dir={'iniesta': 'iniesta', 'commands': 'commands'},
    include_package_data=True,
    install_requires=[
        'insanic',
        'aiobotocore',
        'aioredlock'
    ],
    tests_require=test_requires,
    license='MIT',
    zip_safe=False,
    keywords='iniesta',
    extras_require={
        "development": test_requires,
        "release": ["zest.releaser[recommended]", "flake8"],
        "deploy": ["Click>=6.0"]
    },
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.6',
    ],
    entry_points={
        'console_scripts': [
            'iniesta=iniesta.cli:cli',
        ],
    },
)
