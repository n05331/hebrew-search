# תרומה לפרויקט

תודה על העניין! כך תורמים בצורה מסודרת:

## סביבת פיתוח

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

cd frontend
npm install
npm run build
cd ..

python main.py
```

לפיתוח ממשק חי: `python -m uvicorn backend.server:app --port 8756` במקביל
ל-`npm run dev` בתיקיית `frontend`.

## תהליך עבודה

1. פתחו Issue המתאר את הבאג/הפיצ'ר לפני עבודה גדולה.
2. צרו branch מ-`main` בשם תיאורי: `fix/pdf-columns`, `feat/toc-tree`.
3. שמרו על commits קטנים וממוקדים עם הודעות ברורות (עברית או אנגלית).
4. ודאו שהאפליקציה עולה ושהחיפוש עובד לפני פתיחת Pull Request.
5. פתחו PR מול `main` עם תיאור קצר של השינוי והסיבה.

## גרסאות

הפרויקט מתנהל לפי SemVer. שחרור גרסה = עדכון `CHANGELOG.md`, עדכון מספר
הגרסה (`backend/server.py` ו-`frontend/package.json`), ותיוג `vX.Y.Z` -
ה-CI בונה EXE ומצרף אותו ל-Release אוטומטית.

## סגנון קוד

- Python: קוד קריא, תיעוד בעברית במודולים ציבוריים, ללא תלות חדשה בלי צורך אמיתי.
- React: קומפוננטות פונקציונליות עם hooks, עברית ב-UI, RTL תמיד.
