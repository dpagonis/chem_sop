"""
ChemSOP - WSU Lab Management System

A web application for chemistry lab SOP version control/approval 
and electronic lab notebook with PIN-based signature authentication.
"""

__version__ = "0.1.0"
__author__ = "Demetrios Pagonis"

# Import main components for easier access
from .database import db, init_db
from .sop_utils import (
    generate_sop_id,
    create_sop_directory,
    get_sop_directory,
    save_sop_file,
    save_approved_version,
    load_approved_procedure,
    format_diff_html,
    move_sop_directory,
    parse_markdown_sections,
    build_markdown_from_sections,
    STANDARD_SOP_SECTIONS,
    sanitize_filename
)

__all__ = [
    'db',
    'init_db',
    'generate_sop_id',
    'create_sop_directory',
    'get_sop_directory',
    'save_sop_file',
    'save_approved_version',
    'load_approved_procedure',
    'format_diff_html',
    'move_sop_directory',
    'parse_markdown_sections',
    'build_markdown_from_sections',
    'STANDARD_SOP_SECTIONS',
    'sanitize_filename',
]
