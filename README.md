# WSU Lab Management System

A web application for chemistry lab SOP version control/approval and electronic lab notebook with PIN-based signature authentication.

## Features

- PIN-based signature authentication (no traditional login)
- User role management (Admin, Faculty, Lab Manager, General)
- User approval workflow
- SOP version control and approval workflow
- Electronic lab notebook functionality

## Installation

1. Install dependencies:
```
pip install -r requirements.txt
```

2. Start the server:
```
python app.py
```

3. Open your browser to `http://localhost:3000`

4. **First Time Setup**: When you first run the application, you'll be prompted to create an administrator account. Follow the on-screen instructions to set up your admin name and PIN.

## User Roles

- **Admin**: Can approve all role requests (lab manager, faculty, and general)
- **Faculty**: Can approve faculty and general requests
- **Lab Manager**: Can approve all role requests (lab manager, faculty, and general)
- **General**: Standard user role, requires approval by faculty, lab manager, or admin

## Security Considerations

### PIN-Only Authentication

This system uses PIN-only authentication (no usernames) to prioritize ease of use for laboratory environments. This design choice has the following characteristics:

**Known Limitations:**
- PINs are not checked for uniqueness across users
- If someone attempts to register with another user's PIN, they will discover that PIN is in use
- There is no built-in mechanism to detect or prevent PIN reuse attempts
- Users cannot change their PINs after account creation through the UI

**Recommended Deployment Practices:**
1. **Server-Level Access Control**: Deploy behind institutional authentication (VPN, campus network, etc.)
2. **PIN Complexity**: Encourage users to create longer PINs (8-10+ characters) with mixed types
3. **Physical Security**: Ensure workstations are in controlled access areas
4. **Regular Review**: Periodically audit user accounts for suspicious activity via approval logs
5. **Data Sensitivity**: This system is designed for non-sensitive laboratory documentation (SOPs, procedures)

**PIN Requirements:**
- Minimum 6 characters
- Must contain at least 3 different characters
- Can include numbers, letters, and special characters

### Intended Use Case

This application is designed for laboratory standard operating procedures and documentation that:
- Are not confidential or sensitive
- Are protected by institutional network access controls
- Benefit from streamlined, username-free authentication
- Require digital signatures and approval workflows

**Not recommended for:** Sensitive data, HIPAA/PHI information, export-controlled data, or environments without network-level access controls.

