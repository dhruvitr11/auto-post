import os, io, json, random, base64, time, textwrap, datetime as dt
from zoneinfo import ZoneInfo
import requests
from PIL import Image, ImageDraw, ImageFont

TZ = ZoneInfo("America/New_York")
STATE = "state.json"
INSTRUCTIONS_PROMPT = os.environ["IMAGE_PROMPT"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
CF_ID = os.environ["CF_ACCOUNT_ID"]
CF_TOKEN = os.environ["CF_API_TOKEN"]
FB_ID = os.environ["FB_PAGE_ID"]
FB_TOKEN = os.environ["FB_PAGE_TOKEN"]

GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-flash-latest",
]


def call_cloudflare_text(prompt_text):
    print("Gemini busy -> Switching to Cloudflare Llama AI...", flush=True)
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ID}/ai/run/@cf/meta/llama-3.3-70b-instruct-fp8-fast"
    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Output ONLY valid JSON, no markdown, no extra text."},
            {"role": "user", "content": prompt_text}
        ]
    }
    res = requests.post(
        url,
        headers={"Authorization": f"Bearer {CF_TOKEN}"},
        json=payload,
        timeout=60
    )
    res.raise_for_status()
    return res.json()["result"]["response"].strip()


def call_gemini(parts, fallback_text_prompt=None):
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }

    last_error = None
    for model in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        try:
            print(f"Trying {model}...", flush=True)
            res = requests.post(url, json=payload, timeout=25)
            if res.status_code == 200:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text:
                    return text
            else:
                print(f"{model} error {res.status_code}", flush=True)
                last_error = f"{res.status_code}"
        except Exception as e:
            print(f"{model} timeout: {e}", flush=True)
            last_error = str(e)

    if fallback_text_prompt:
        return call_cloudflare_text(fallback_text_prompt)

    raise RuntimeError(f"All AI models failed: {last_error}")


def generate_news_package():
    print("Step 1: Generating news topic, visual prompt, and banner text...", flush=True)
    prompt_instruction = (
        f"You are an expert news visual director. Read these guidelines:\n"
        f"{INSTRUCTIONS_PROMPT}\n\n"
        f"TASK: Select ONE fresh trending US news topic and return ONLY a valid JSON object with these 3 exact keys:\n"
        f'1. "visual_prompt": A concise photorealistic image prompt (40-50 words) for Flux-1-schnell focusing ONLY on people, setting, and action. CRITICAL: Do NOT include any text, banners, signs, or words inside the image prompt.\n'
        f'2. "headline": A short punchy uppercase news headline (5 to 7 words max, e.g., "US GAS PRICES SURGE TO RECORD HIGHS").\n'
        f'3. "subtitle": A crisp uppercase sub-headline (8 to 12 words max summarizing the key fact).\n'
        f"Output ONLY raw JSON, no markdown code blocks."
    )

    raw = call_gemini([{"text": prompt_instruction}], fallback_text_prompt=prompt_instruction)
    raw = raw.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)

    print("Visual Prompt:", data["visual_prompt"], flush=True)
    print("Headline:", data["headline"], flush=True)
    print("Subtitle:", data["subtitle"], flush=True)
    return data["visual_prompt"], data["headline"].upper(), data["subtitle"].upper()


def add_news_banner(img_bytes, headline, subtitle):
    print("Step 2.5: Adding clean red news banner and crisp text...", flush=True)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = img.size

    banner_h = int(h * 0.22)
    new_img = Image.new("RGB", (w, h + banner_h), (195, 22, 28))  # Deep Breaking News Red
    new_img.paste(img, (0, 0))

    draw = ImageDraw.Draw(new_img)

    # Ubuntu / Linux પર ઉપલબ્ધ બોલ્ડ ફોન્ટ લોડ કરો
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    font_path = next((p for p in font_paths if os.path.exists(p)), None)

    head_size = int(w * 0.052)
    sub_size = int(w * 0.025)

    head_font = ImageFont.truetype(font_path, head_size) if font_path else ImageFont.load_default()
    sub_font = ImageFont.truetype(font_path, sub_size) if font_path else ImageFont.load_default()

    # Headline ને 2 લાઈનમાં સેટ કરો
    wrapped_head = textwrap.fill(headline, width=26)
    head_bbox = draw.multiline_textbbox((0, 0), wrapped_head, font=head_font, align="center")
    head_w = head_bbox[2] - head_bbox[0]
    head_h = head_bbox[3] - head_bbox[1]

    # Subtitle ને 1-2 લાઈનમાં સેટ કરો
    wrapped_sub = textwrap.fill(subtitle, width=56)
    sub_bbox = draw.multiline_textbbox((0, 0), wrapped_sub, font=sub_font, align="center")
    sub_w = sub_bbox[2] - sub_bbox[0]
    sub_h = sub_bbox[3] - sub_bbox[1]

    total_text_h = head_h + int(banner_h * 0.08) + sub_h
    start_y = h + (banner_h - total_text_h) // 2

    draw.multiline_text(
        ((w - head_w) // 2, start_y),
        wrapped_head,
        font=head_font,
        fill=(255, 255, 255),
        align="center"
    )
    draw.multiline_text(
        ((w - sub_w) // 2, start_y + head_h + int(banner_h * 0.08)),
        wrapped_sub,
        font=sub_font,
        fill=(255, 255, 255),
        align="center"
    )

    out = io.BytesIO()
    new_img.save(out, format="JPEG", quality=95)
    return out.getvalue()


def make_image():
    short_prompt, headline, subtitle = generate_news_package()
    print("Step 2: Generating clean photo with Cloudflare Flux...", flush=True)

    payload = {
        "prompt": short_prompt,
        "steps": 4
    }

    r = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ID}/ai/run/@cf/black-forest-labs/flux-1-schnell",
        headers={"Authorization": f"Bearer {CF_TOKEN}"},
        json=payload,
        timeout=120,
    )
    if r.status_code != 200:
        print("Cloudflare Error Details:", r.text, flush=True)
    r.raise_for_status()

    raw_img = base64.b64decode(r.json()["result"]["image"])
    final_img = add_news_banner(raw_img, headline, subtitle)
    print("Final News Graphic Ready!", flush=True)
    return final_img, f"{headline} - {subtitle}"


def make_caption(img, news_summary):
    print("Step 3: Generating Facebook caption...", flush=True)
    b64_img = base64.b64encode(img).decode("utf-8")
    caption_instruction = (
        f"Look at this news image ({news_summary}) and write a Facebook post for it: "
        "a catchy title on the first line, then a short engaging "
        "description (2-3 sentences), then 8 relevant hashtags on "
        "the last line. Plain text only, no markdown, no asterisks."
    )
    parts = [
        {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}},
        {"text": caption_instruction}
    ]

    text = call_gemini(parts, fallback_text_prompt=caption_instruction)
    print("Caption Ready!", flush=True)
    return text


def post_fb(img, caption):
    print("Step 4: Uploading post to Facebook...", flush=True)
    url = f"https://graph.facebook.com/v21.0/{FB_ID}/photos"
    data = {
        "caption": caption,
        "access_token": FB_TOKEN
    }
    files = {
        "source": ("post.jpg", img, "image/jpeg")
    }

    r = requests.post(url, data=data, files=files, timeout=120)
    if r.status_code != 200:
        print("Facebook Error Details:", r.text, flush=True)
    r.raise_for_status()

    print("Posted successfully:", r.json(), flush=True)


def make_schedule(today, now):
    start = max(dt.datetime.combine(today, dt.time(6, 0), tzinfo=TZ), now)
    best = []
    for _ in range(500):
        t = start + dt.timedelta(minutes=random.randint(10, 90))
        times = [t]
        for _ in range(11):
            t += dt.timedelta(minutes=random.randint(40, 120))
            times.append(t)
        times = [x for x in times if x.date() == today]
        if len(times) > len(best):
            best = times
        if len(best) == 12:
            break
    return [x.isoformat() for x in best]


def main():
    now = dt.datetime.now(TZ)

    if os.environ.get("FORCE") == "yes":
        print("FORCE run triggered: bypassing schedule...", flush=True)
        img, news_summary = make_image()
        caption = make_caption(img, news_summary)
        post_fb(img, caption)
        return

    try:
        state = json.load(open(STATE))
    except Exception:
        state = {"date": "", "times": [], "done": []}

    if state["date"] != str(now.date()):
        if now.hour < 6:
            print("6 AM pehla, wait.", flush=True)
            return
        state = {
            "date": str(now.date()),
            "times": make_schedule(now.date(), now),
            "done": [],
        }
        print("Aajna times:", state["times"], flush=True)

    for i, t in enumerate(state["times"]):
        if i not in state["done"] and dt.datetime.fromisoformat(t) <= now:
            img, news_summary = make_image()
            caption = make_caption(img, news_summary)
            post_fb(img, caption)
            state["done"].append(i)
            break

    json.dump(state, open(STATE, "w"), indent=2)


if __name__ == "__main__":
    main()
