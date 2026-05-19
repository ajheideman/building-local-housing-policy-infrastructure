#Notes

Python script checks RoboFlow Universe first, then fills gaps with Bing.

To get it running:

Step 1 — Get Bing API key. Go to portal.azure.com → Create a resource → search "Bing Search v7" → Free tier (F0). You'll get a key you paste into BING_API_KEY at the top of the script.

Step 2 — Install dependencies (pip install requests pillow tqdm)

Step 3 — Run python collect_images.py

It will create an images/ folder with five subfolders — one per repair category — and fill each with 200 JPEGs.
