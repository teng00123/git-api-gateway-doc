---
name: git-api-gateway-doc
description: Scan git diff for new or modified API interfaces and generate gateway documentation in standardized format. Use when user requests API documentation generation from git changes, asks to document new endpoints, or needs gateway docs for recent interface modifications. Triggers on phrases like "generate gateway docs from git diff", "document new APIs", "scan git for interface changes", "API gateway documentation" etc.
---

# Git Api Gateway Doc

## Overview

Automatically scan git diff output to identify new or modified API endpoints and generate standardized gateway documentation. Processes controller files, extracts interface definitions, and outputs documentation in consistent format.

## Workflow

### Step 1: Get Git Diff
Collect git diff output for the target branch/commit range:
- `git diff HEAD~1` (last commit)
- `git diff main..feature-branch` (branch comparison)
- `git diff --cached` (staged changes)

### Step 2: Parse Interface Changes
Identify API interface modifications:
- New controller classes/methods
- Modified endpoint paths
- Changed HTTP methods
- Updated request/response schemas

### Step 3: Extract Interface Details
For each new/modified API:
- HTTP method and path
- Function name and parameters
- Request body schema
- Response format
- Authentication requirements

### Step 4: Generate Gateway Documentation
Output documentation in standardized format:
- Interface overview table
- Detailed endpoint descriptions
- Request/response examples
- Error code mappings

## Resources

### scripts/
- `parse_git_diff.py`: Main script to parse git diff and generate documentation

### references/
- `gateway-format-spec.md`: Standard format specification for gateway documentation

## Usage Examples

**Request**: "Generate gateway docs from git diff"
1. Run: `git diff HEAD~1 > changes.diff`
2. Execute: `python scripts/parse_git_diff.py changes.diff`
3. Output: Formatted gateway documentation

**Request**: "Document new APIs in feature branch"  
1. Run: `git diff main..feature-branch > changes.diff`
2. Execute parser script
3. Review generated documentation

## Resources (optional)

Create only the resource directories this skill actually needs. Delete this section if no resources are required.

### scripts/
Executable code (Python/Bash/etc.) that can be run directly to perform specific operations.

**Examples from other skills:**
- PDF skill: `fill_fillable_fields.py`, `extract_form_field_info.py` - utilities for PDF manipulation
- DOCX skill: `document.py`, `utilities.py` - Python modules for document processing

**Appropriate for:** Python scripts, shell scripts, or any executable code that performs automation, data processing, or specific operations.

**Note:** Scripts may be executed without loading into context, but can still be read by Codex for patching or environment adjustments.

### references/
Documentation and reference material intended to be loaded into context to inform Codex's process and thinking.

**Examples from other skills:**
- Product management: `communication.md`, `context_building.md` - detailed workflow guides
- BigQuery: API reference documentation and query examples
- Finance: Schema documentation, company policies

**Appropriate for:** In-depth documentation, API references, database schemas, comprehensive guides, or any detailed information that Codex should reference while working.

### assets/
Files not intended to be loaded into context, but rather used within the output Codex produces.

**Examples from other skills:**
- Brand styling: PowerPoint template files (.pptx), logo files
- Frontend builder: HTML/React boilerplate project directories
- Typography: Font files (.ttf, .woff2)

**Appropriate for:** Templates, boilerplate code, document templates, images, icons, fonts, or any files meant to be copied or used in the final output.

---

**Not every skill requires all three types of resources.**
