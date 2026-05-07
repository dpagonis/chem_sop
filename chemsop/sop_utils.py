import os
import uuid
from datetime import datetime
import difflib
import re

# Standard SOP sections (in order)
STANDARD_SOP_SECTIONS = [
    'Lab Description',
    'Reagent list',
    'Chemicals to prepare',
    'Laboratory setup',
    'Waste streams'
]

def generate_sop_id():
    """Generate a unique SOP ID"""
    return f"SOP-{uuid.uuid4().hex[:8].upper()}"

def get_sop_directory(sop_id, status, course=None):
    """Get the directory path for a specific SOP based on its status"""
    base_dir = 'SOPs'
    
    if status == 'draft':
        # Drafts go in Drafts folder
        return os.path.join(base_dir, 'Drafts', sop_id)
    elif status == 'submitted':
        # Submitted SOPs go in Submitted folder
        return os.path.join(base_dir, 'Submitted', sop_id)
    elif status == 'approved' and course:
        # Approved SOPs go in their course folder
        return os.path.join(base_dir, sanitize_filename(course), sop_id)
    else:
        # Default to base directory with SOP ID
        return os.path.join(base_dir, sop_id)

def sanitize_filename(name):
    """Sanitize a string to be used as a filename"""
    # Replace invalid characters with underscores
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name.strip()

def create_sop_directory(sop_id, status, course=None):
    """Create the directory structure for a SOP based on its status"""
    sop_dir = get_sop_directory(sop_id, status, course)
    os.makedirs(sop_dir, exist_ok=True)
    return sop_dir

def move_sop_directory(sop_id, old_status, new_status, old_course=None, new_course=None):
    """Move a SOP directory from one location to another based on status change"""
    import shutil
    
    old_dir = get_sop_directory(sop_id, old_status, old_course)
    new_dir = get_sop_directory(sop_id, new_status, new_course)
    
    # Only move if directories are different and old directory exists
    if old_dir != new_dir and os.path.exists(old_dir):
        os.makedirs(os.path.dirname(new_dir), exist_ok=True)
        shutil.move(old_dir, new_dir)
    
    return new_dir

def save_sop_file(sop_id, status, course, procedure):
    """Save the current procedure to a markdown file"""
    sop_dir = get_sop_directory(sop_id, status, course)
    os.makedirs(sop_dir, exist_ok=True)
    
    procedure_file = os.path.join(sop_dir, 'procedure.md')
    with open(procedure_file, 'w', encoding='utf-8') as f:
        f.write(procedure or '')
    
    return procedure_file

def save_approved_version(sop_id, course, procedure, status='approved'):
    """Save the approved version of the procedure in the SOP's current directory"""
    sop_dir = get_sop_directory(sop_id, status, course)
    os.makedirs(sop_dir, exist_ok=True)
    
    approved_file = os.path.join(sop_dir, 'approved_procedure.md')
    with open(approved_file, 'w', encoding='utf-8') as f:
        f.write(procedure or '')
    
    return approved_file

def load_approved_procedure(sop_id, course, status='approved'):
    """Load the approved version of the procedure from the SOP's directory"""
    sop_dir = get_sop_directory(sop_id, status, course)
    approved_file = os.path.join(sop_dir, 'approved_procedure.md')
    
    # Try .md first, fall back to .txt for backward compatibility
    if os.path.exists(approved_file):
        with open(approved_file, 'r', encoding='utf-8') as f:
            return f.read()
    
    # Check for legacy .txt file
    legacy_file = os.path.join(sop_dir, 'approved_procedure.txt')
    if os.path.exists(legacy_file):
        with open(legacy_file, 'r', encoding='utf-8') as f:
            return f.read()
    
    return ''

def parse_markdown_sections(markdown_text, title=''):
    """
    Parse markdown text into sections based on ## headings.
    Returns a dictionary with section names as keys and content as values.
    Also includes the title (# heading) if present.
    """
    sections = {}
    
    if not markdown_text:
        # Return empty sections
        return {section: '' for section in STANDARD_SOP_SECTIONS}
    
    lines = markdown_text.split('\n')
    current_section = None
    current_content = []
    
    for line in lines:
        # Check for H1 (title) - extract but don't include in sections
        if line.startswith('# ') and not line.startswith('## '):
            continue
        # Check for H2 (section heading)
        elif line.startswith('## '):
            # Save previous section if any
            if current_section:
                sections[current_section] = '\n'.join(current_content).strip()
            
            # Start new section
            current_section = line[3:].strip()
            current_content = []
        else:
            # Add content to current section
            if current_section:
                current_content.append(line)
    
    # Save last section
    if current_section:
        sections[current_section] = '\n'.join(current_content).strip()
    
    # Ensure all standard sections exist
    for section in STANDARD_SOP_SECTIONS:
        if section not in sections:
            sections[section] = ''
    
    return sections

def build_markdown_from_sections(title, sections):
    """
    Build a complete markdown document from title and sections.
    Title becomes H1, sections become H2 headings.
    """
    lines = []
    
    # Add title as H1
    if title:
        lines.append(f'# {title}')
        lines.append('')
    
    # Add each section as H2
    for section_name in STANDARD_SOP_SECTIONS:
        content = sections.get(section_name, '').strip()
        lines.append(f'## {section_name}')
        lines.append('')
        if content:
            lines.append(content)
        lines.append('')
    
    return '\n'.join(lines)

def generate_diff(old_text, new_text):
    """Generate a unified diff between two texts"""
    old_lines = (old_text or '').splitlines(keepends=True)
    new_lines = (new_text or '').splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        old_lines, 
        new_lines,
        fromfile='Approved Version',
        tofile='Current Draft',
        lineterm=''
    )
    
    return ''.join(diff)

def format_diff_html(old_text, new_text):
    """Generate HTML formatted diff in inline style with +/- and green/red colors"""
    old_lines = (old_text or '').splitlines()
    new_lines = (new_text or '').splitlines()
    
    # Generate unified diff
    diff_lines = list(difflib.unified_diff(old_lines, new_lines, lineterm=''))
    
    if not diff_lines:
        return '<p style="color: #666;">No changes detected</p>'
    
    html_parts = ['<div style="font-family: monospace; font-size: 14px; line-height: 1.5;">']
    
    for line in diff_lines:
        if line.startswith('---') or line.startswith('+++'):
            continue  # Skip file headers
        elif line.startswith('@@'):
            # Context header
            html_parts.append(f'<div style="color: #666; background: #f0f0f0; padding: 5px; margin-top: 10px;">{line}</div>')
        elif line.startswith('-'):
            # Removed line
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f'<div style="background: #fdd; color: #d00; padding: 2px 5px; border-left: 3px solid #d00;">{escaped}</div>')
        elif line.startswith('+'):
            # Added line
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f'<div style="background: #dfd; color: #0a0; padding: 2px 5px; border-left: 3px solid #0a0;">{escaped}</div>')
        else:
            # Context line
            escaped = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f'<div style="color: #333; padding: 2px 5px;">{escaped}</div>')
    
    html_parts.append('</div>')
    return ''.join(html_parts)
