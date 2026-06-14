import os, subprocess, glob

# Config
TESSDATA_PREFIX = "C:/Users/nil28/trade/tessdata"
TESSERACT_EXE = "C:/Program Files/Tesseract-OCR/tesseract.exe"
IMG_DIR = "C:/Users/nil28/trade/fibdiv"
OUT_DIR = "C:/Users/nil28/trade/fibdiv_text"

os.makedirs(OUT_DIR, exist_ok=True)

# Get sorted list of PNG files
files = sorted(glob.glob(os.path.join(IMG_DIR, "*.png")))
print(f"Total screenshots: {len(files)}")

# Process screenshots 42-53 (indices 41-52)
start = 41
end = 53
target_files = files[start:end]
print(f"Processing screenshots {start+1}-{end} ({len(target_files)} files)")

combined_text = []

for i, fpath in enumerate(target_files, start=start+1):
    fname = os.path.basename(fpath)
    out_base = os.path.join(OUT_DIR, f"screen_{i:02d}")
    cmd = [
        TESSERACT_EXE,
        fpath,
        out_base,
        "-l", "rus+eng",
        "--psm", "6"
    ]
    env = os.environ.copy()
    env["TESSDATA_PREFIX"] = TESSDATA_PREFIX

    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(f"  ERROR on {fname}: {result.stderr.strip()}")
        continue

    txt_path = out_base + ".txt"
    with open(txt_path, "r", encoding="utf-8") as tf:
        text = tf.read().strip()

    header = f"=== Screenshot {i}: {fname} ==="
    print(header)
    combined_text.append(header + "\n" + text + "\n")

# Save combined
combined_path = os.path.join(OUT_DIR, "combined_42_53.txt")
with open(combined_path, "w", encoding="utf-8") as f:
    f.write("\n".join(combined_text))

print(f"\nDone. Combined text saved to: {combined_path}")
