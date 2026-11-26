# Splendour Vessel Intelligence — Business Development User Guide

Welcome to Splendour Vessel Intelligence. This web application helps the Business Development (BD) team track incoming commercial vessels, evaluate hull cleaning opportunities, and manage customer communications through our business pipeline.

---

## 1. Access & Roles

### Signing In
Navigate to the web application URL and sign in using your assigned username and password.

### User Roles
- **BD Manager**: Can view all vessel arrivals, filter and search opportunities, open vessel dossiers, update opportunity pipeline stages, add notes, and download lead spreadsheets (CSV).
- **Admin**: Has all BD Manager capabilities plus access to the Django administration dashboard to configure user accounts, ports, and system parameters.

### What to do if you see "Access Denied" (403 Page)
If you sign in and see an "Access Denied" message stating that your account has no assigned role, contact your system administrator. Your user account exists but needs to be added to either the **BD Manager** or **Admin** user group.

---

## 2. The Lead Board

The home page displays incoming commercial vessel opportunities arranged across three arrival columns based on expected transit windows:
- **24 hour priority**: Vessels estimated to arrive within the next 24 hours. These require immediate BD review and outreach.
- **72 hour approach**: Vessels expected between 24 and 72 hours out. Use this column to prepare quotes and research ownership.
- **Anchorage / port**: Vessels currently stationed at anchorage or within the port limits.

### Priority Score Bands
Every vessel arrival is evaluated by an automated scoring model:
- **HOT (Score 80 and above)**: High-priority target segment (e.g. large tankers, bulk carriers, container ships) with urgent commercial opportunity.
- **HIGH (Score 60 to 79)**: Strong commercial candidate.
- **MEDIUM (Score 40 to 59)**: Standard commercial inquiry.
- **LOW (Score below 40)**: Smaller tonnage or lower likelihood of commercial engagement.

### Filters and the "Reset Filters" Button
- **Port**: Filter by target port (e.g., Singapore, Fujairah).
- **Priority Band**: View only HOT, HIGH, MEDIUM, or LOW opportunities.
- **Stage**: Filter by current pipeline stage (e.g., Detected, Qualifying, Contacted).
- **Search**: Find vessels quickly by name, IMO number, or MMSI.
- **Sort**: Order leads by "Highest score" (default) or "Soonest ETA".
- **Inbound only**: Restrict results to vessels confirmed en route to port.
- **Include closed leads**: By default, leads marked as Won or Lost are hidden. Check this box to view completed or archived leads.
- **Reset filters**: Restores all filters to standard defaults in one click and announces the reset. The button automatically disables when default settings are already active.

### Exporting to CSV
Click **Export CSV** in the filter bar to download the current filtered list as a spreadsheet compatible with Microsoft Excel and Google Sheets. The export respects all active filters and caps downloads at 5,000 rows to ensure fast response times.

---

## 3. Reading Lead Cards & Important Cautions

Each lead card displays the vessel name, priority band badge, score, port, ETA, and the rationale behind the lead score. Keep these key considerations in mind:
- **ETAs are estimates**: Arrival times are calculated based on reported AIS signals and provider forecasts. Weather, port congestion, and bunkering delays can shift schedules. If a card displays "ETA passed", the estimated window has expired and the vessel should be checked in the port or anchorage view.
- **All times are UTC**: Every timestamp displayed across the application is recorded in Coordinated Universal Time (UTC).
- **Public and unverified data**: Information is derived from public maritime AIS signals and third-party commercial databases. Always verify vessel identity and specifications with ship owners or port agents prior to contractual commitments.
- **Vessels without ownership records**: Newly detected vessels may temporarily display "Owner and manager data is not available yet" while automatic enrichment is pending.

---

## 4. The Vessel & Lead Detail Pages

### Full Vessel Dossier
Clicking any vessel name opens its comprehensive profile, including technical particulars (length, beam, draught, gross tonnage, deadweight), current voyage details, position history, and corporate relationships (commercial operator, technical manager, registered owner).

### Pipeline Stages & Moving Leads
On the Lead Page, the pipeline progress bar shows where the vessel stands:
- **Main path**: Detected &rarr; Qualifying &rarr; Ready For Review &rarr; Contacted &rarr; Replied &rarr; Quote Requested &rarr; Quoted &rarr; Negotiation &rarr; Won.
- **Side states**: Follow Up Later or Lost.

When marking a lead as **Won** or **Lost**, a confirmation dialog appears to ensure deliberate closure. Closing a lead removes it from the active lead board until new arrival observations are logged.

### Notes & Transition History
- **Add Notes**: Record meeting outcomes, call summaries, and price indications in the Notes card.
- **Stage Transition Notes**: You can provide an optional explanation directly when changing a stage. It will be posted automatically to the Notes log.
- **Conflict Handling**: If two BD team members change the same lead simultaneously, the second submitter is alerted that the record was updated by a colleague, and their note text is safely preserved in the input box so no work is lost.

---

## 5. What the Application Does NOT Do

- **No automated messaging**: This application does not send emails, WhatsApp messages, or telexes to vessel owners or agents.
- **Human-in-the-loop outreach**: Any communication to ship managers, technical operators, or agents must be drafted, verified, and sent directly by a member of the BD team.

---

## 6. Troubleshooting

- **Page stuck on "Loading..."**: If network connectivity was briefly interrupted or a cached script was retained, perform a hard browser refresh: press **Ctrl + Shift + R** (Windows) or **Cmd + Shift + R** (Mac). If the issue persists, click the "Retry" button on the card.
- **403 Forbidden Screen**: Your session may have expired or your account may need role reassignment. Sign out and sign back in, or contact an administrator.
- **Opening CSV in Microsoft Excel**: The exported CSV file uses UTF-8 formatting and standard comma delimiters. Excel opens it directly; formulas and special characters are safely neutralized.

