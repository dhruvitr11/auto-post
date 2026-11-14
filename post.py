import os, json, random, base64, datetime as dt
from zoneinfo import ZoneInfo
import requests

TZ = ZoneInfo("America/New_York")
STATE = "state.json"
INSTRUCTIONS_PROMPT = os.environ["IMAGE_PROMPT"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
CF_ID = os.environ["CF_ACCOUNT_ID"]
CF_TOKEN = os.environ["CF_API_TOKEN"]
FB_ID = os.environ["FB_PAGE_ID"]
FB_TOKEN = os.environ["FB_PAGE_TOKEN"]
GEMINI_MODEL = "gemini-3.8-flash"


def generate_visual_prompt():
    print("Step 1: Generating visual prompt with Gemini...", flush=True)
    prompt_instruction = (
        f"You are an expert news visual director. Read these guidelines:\n"
        f"{INSTRUCTIONS_PROMPT}\n\n"
        f"TASK: Select ONE trending US news topic. Write a concise, photorealistic, "
        f"descriptive image prompt (max 40-50 words) suitable for Flux-1-schnell. "
        f"Focus only on visual elements: people, setting, lighting, cinematic style, "
        f"and editorial atmosphere. Output ONLY the raw prompt text, no intro, no quotes."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt_instruction}]}],
        "generationConfig": {
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }

    res = requests.post(url, json=payload, timeout=60)
    if res.status_code != 200:
        print("Gemini Prompt Error:", res.status_code, res.text, flush=True)
    res.raise_for_status()

    data = res.json()
    visual_prompt = data["candidates"][0]["content"]["parts"][0]["text"].strip().replace("\n", " ")
    if not visual_prompt:
        raise ValueError("Gemini returned empty visual prompt")

    print("Visual Prompt Ready:", visual_prompt, flush=True)
    return visual_prompt


def make_image():
    short_prompt = generate_visual_prompt()
    print("Step 2: Generating image with Cloudflare Flux...", flush=True)

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

    print("Image Ready!", flush=True)
    return base64.b64decode(r.json()["result"]["image"])


def make_caption(img):
    print("Step 3: Generating caption with Gemini...", flush=True)
    b64_img = base64.b64encode(img).decode("utf-8")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg", "data": b64_img}},
                {"text": (
                    "Look at this image and write a Facebook post for it: "
                    "a catchy title on the first line, then a short engaging "
                    "description (2-3 sentences), then 8 relevant hashtags on "
                    "the last line. Plain text only, no markdown, no asterisks."
                )}
            ]
        }],
        "generationConfig": {
            "thinkingConfig": {"thinkingBudget": 0}
        }
    }
    res = requests.post(url, json=payload, timeout=60)
    if res.status_code != 200:
        print("Gemini Caption Error:", res.status_code, res.text, flush=True)
    res.raise_for_status()

    data = res.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if not text:
        raise ValueError("Gemini returned empty caption")

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
        img = make_image()
        caption = make_caption(img)
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
            img = make_image()
            caption = make_caption(img)
            post_fb(img, caption)
            state["done"].append(i)
            break

    json.dump(state, open(STATE, "w"), indent=2)


if __name__ == "__main__":
    main()
