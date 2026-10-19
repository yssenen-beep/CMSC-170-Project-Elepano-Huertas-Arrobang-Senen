import requests

url = "https://api-amis.uplb.edu.ph/api/students/classes?page=1&items=5&status=Active&by_term_type=true&term_id=1252&course_code_like=--&section_like=--&class_status=--"

headers = {
    "Authorization": "Bearer 12312482|wTvHxdANN8ZYCebWdSuzxXDAjKDgQrEJfQmEMHjU",
    "x-session-id": "587fc47d-6bda-4374-97c6-6c050530f151",
    "Accept": "application/json",
}

params = {
    "page": 1,
    "items": 12458,
    "status": "Active",
    "by_term_type": "true",
    "term_id": 1261,
    "course_code_like": "--",
    "section_like": "--",
    "class_status": "--",
}

response = requests.get(
    url,
    headers=headers,
    params=params,
    timeout=30,
)

with open("classes_second_sem.json", "w", encoding="utf-8") as file:
    file.write(response.text)

print("Saved to classes.json")
