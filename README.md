# ChemSOP

Web application for chemistry lab SOP version control and approval workflow with PIN-based authentication.

## Features

- PIN-based signature authentication
- User role management (Admin, Faculty, Lab Manager, General)
- SOP version control and approval workflow

## Installation

```bash
pip install chemsop
```

## Usage

```bash
chemsop
```

Open your browser to `http://localhost:3000`

**First run**: You'll be prompted to create an administrator account.

## User Roles

- **Admin/Lab Manager**: Approve all role requests
- **Faculty**: Approve faculty and general requests
- **General**: Standard user (requires approval)

## Security Notes

- Uses PIN-only authentication (no usernames)
- Deploy behind institutional network access (VPN, campus network)
- Designed for non-sensitive lab documentation only

