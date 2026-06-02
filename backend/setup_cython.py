"""setup.py for Cython compilation of critical security modules."""
import os
import sys
from setuptools import setup, Extension
from Cython.Build import cythonize

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

extensions = [
    Extension('license', ['license.py']),
    Extension('crypto', ['crypto.py']),
    Extension('hwid', ['hwid.py']),
]

setup(
    name='ai_grade_core',
    ext_modules=cythonize(
        extensions,
        compiler_directives={'language_level': '3'},
    ),
)
