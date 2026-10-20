import requests

url = "https://api-amis.uplb.edu.ph/api/curriculums"

headers = {
    "Authorization": "",
    "x-session-id": "",
    "Accept": "application/json",
}

params = {
    "page": 1,
    "items": 174,
    "w_curriculum_details": "true",
    "curriculum_details": "true",
    "code_like": "--",
    "name_like": "--",
}

response = requests.get(
    url,
    headers=headers,
    params=params,
    timeout=30,
)

with open("classes_midyear_sem.json", "w", encoding="utf-8") as file:
    file.write(response.text)

print("Saved to classes.json")
