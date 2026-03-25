Running Order Web App — URL Only

This version is URL-only.
There is no laptop/offline Wi-Fi mode in this build.

What it does
- Hosted web app for any smartphone
- Viewer mode at the normal URL
- Admin mode at ?mode=admin with PIN
- Blue Search 1 and Red Search 2 split-screen
- QR codes for Viewer and Admin hosted URLs
- Event info banner
- Edit Running Order panel

Deploy
1) Put these files in a GitHub repo
2) Deploy on Streamlit Community Cloud or Render
3) Set environment variable RUNORDER_ADMIN_PIN
4) Open your hosted URL
5) Admin uses: https://your-url/?mode=admin

Notes
- This build assumes internet/cell access.
- Excel format expected: sheet contains a header row with 'Run Number'.
