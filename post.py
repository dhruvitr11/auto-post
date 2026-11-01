import os, json, random, base64, datetime as dt
from zoneinfo import ZoneInfo
import requests
from google import genai
from google.genai import types

TZ = ZoneInfo("America/New_York")
STATE = "state.json"
INSTRUCTIONS_PROMPT = os.environ["IMAGE_PROMPT"]
CF_ID = os.environ["CF_ACCOUNT_ID"]
CF_TOKEN = os.environ["CF_API_TOKEN"]
FB_ID = os.environ["FB_PAGE_ID"]
FB_TOKEN = os.environ["FB_PAGE_TOKEN"]
# ૧. મોડેલનું નામ વધુ સ્ટેબલ રાખો:
GEMINI_MODEL = "gemini-2.5-flash"  # અથવા "gemini-1.5-flash"


def generate_visual_prompt():
    """
    સ્ટેપ ૧: Gemini તમારા લાંબા પ્રોમ્પ્ટ પરથી ટૂંકો વિઝ્યુઅલ પ્રોમ્પ્ટ બનાવશે.
    """
    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        prompt_instruction = (
            f"You are an expert news visual director. Read these guidelines:\n"
            f"{INSTRUCTIONS_PROMPT}\n\n"
            f"TASK: Select ONE trending US news topic. Write a concise, photorealistic, "
            f"descriptive image prompt (max 40-50 words) suitable for Flux-1-schnell. "
            f"Focus only on visual elements: people, setting, lighting, cinematic style, "
            f"and editorial atmosphere. Output ONLY the raw prompt text, no intro, no quotes."
        )

        # સીધો સ્ટ્રિંગ પાસ કરો:
        res = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt_instruction,
        )
        visual_prompt = (res.text or "").strip().replace("\n", " ")
        if visual_prompt:
            print("Gemini Generated Visual Prompt:", visual_prompt)
            return visual_prompt
    except Exception as e:
        print("Gemini prompt generation error:", e)

    return "Cinematic photorealistic news photography, US Capitol and White House background, dramatic lighting, professional editorial shot, 8k"


def make_image():
    """
    સ્ટેપ ૨: Cloudflare Flux ઈમેજ જનરેટ કરશે ('seed' પેરામીટર વગર).
    """
    short_prompt = generate_visual_prompt()

    # અહીથી 'seed' હટાવી લીધું છે જેથી 400 એરર નહીં આવે
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
        print("Cloudflare Error Details:", r.text)
    r.raise_for_status()
    return base64.b64decode(r.json()["result"]["image"])


def make_caption(img):
    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        res = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=img, mime_type="image/jpeg"),
                "Look at this image and write a Facebook post for it: "
                "a catchy title on the first line, then a short engaging "
                "description (2-3 sentences), then 8 relevant hashtags on "
                "the last line. Plain text only, no markdown, no asterisks.",
            ],
        )
        text = (res.text or "").strip()
        if text:
            return text
    except Exception as e:
        print("Gemini error:", e)
    return "Trending US News Update\n\n#news #breaking #usa #daily #updates"





# ૨. post_fb ફંક્શનમાં એરર પ્રિન્ટ ઉમેરો:
def post_fb(img, caption):
    url = f"https://graph.facebook.com/v21.0/{FB_ID}/photos"
    data = {
        "caption": caption,          # Graph API photos એન્ડપોઈન્ટ માટે 'caption' અથવા 'message' ચાલે છે
        "access_token": FB_TOKEN
    }
    files = {
        "source": ("post.jpg", img, "image/jpeg")
    }
    
    r = requests.post(url, data=data, files=files, timeout=120)
    
    # ફેસબુક તરફથી ચોક્કસ શું એરર આવી તે પ્રિન્ટ થશે:
    if r.status_code != 200:
        print("Facebook Error Details:", r.text)
        
    r.raise_for_status()
    print("Posted successfully:", r.json())


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

    # ટેસ્ટિંગ માટે FORCE="yes" હોય તો શેડ્યૂલ ચેક વગર સીધી જ પોસ્ટ કરશે
    if os.environ.get("FORCE") == "yes":
        print("FORCE run triggered: bypassing schedule...")
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
            print("6 AM pehla, wait.")
            return
        state = {
            "date": str(now.date()),
            "times": make_schedule(now.date(), now),
            "done": [],
        }
        print("Aajna times:", state["times"])

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
