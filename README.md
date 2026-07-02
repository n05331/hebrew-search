# חיפוש עברי — תוכנת חיפוש שולחנית בקבצים

Hebrew Search — an offline Windows desktop app for full-text search in Hebrew
documents (PDF, Word, text, scanned images with Hebrew OCR).

תוכנת חיפוש שולחנית ל-Windows, עם דגש חזק על עברית, לחיפוש בתוך קבצים:
Word‏ (docx), ‏PDF, טקסט, ותמונות/סריקות (עם OCR עברי). כל תוצאה מוצגת
בהקשר שלה על המקור, ניתן לפתוח את הקובץ במיקום המדויק, ולייצא לטקסט.
הכל רץ מקומית (offline).

## יכולות עיקריות

- חיפוש טקסט מלא מהיר (מנוע Tantivy, דירוג BM25).
- עברית איכותית: הסרת ניקוד, טיפול באותיות סופיות, תחיליות (ו/ה/ב/כ/ל/מ/ש)
  וסטמינג קל של סיומות — כך ש"ילד" מוצא גם "הילדים".
- חילוץ מ-Word‏, PDF‏, טקסט, HTML, ותמונות.
- OCR עברי מובנה (Tesseract, מנוע ומודל עברית מצורפים ל-EXE).
- הצגת ההקשר על המקור עם הדגשה וניווט בין ההופעות.
- פתיחת הקובץ במיקום (וב-PDF קפיצה לעמוד), הצגה בתיקייה, וייצוא לטקסט.
- מעקב חי אחר שינויי קבצים (עדכון אינדקס מצטבר).
- סינון לפי סוג קובץ ותיקייה, וחיפוש ביטוי מדויק.
- יומן אבחון מובנה + קובצי לוג לאיתור תקלות.

## הרצה מהקוד (למפתחים)

דרישות: Python 3.11+‏, Node.js 18+.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# בניית הממשק
cd frontend
npm install
npm run build
cd ..

# הרצה
python main.py
```

לפיתוח הממשק בזמן אמת: הריצו `python -m uvicorn backend.server:app --port 8756`
ובמקביל `npm run dev` בתיקיית `frontend` (הפרוקסי מפנה ל-8756).

## OCR

ה-EXE הארוז כולל את מנוע Tesseract ואת מודל השפה העברית — אין צורך בהתקנה.
בהרצה מהקוד: התקינו Tesseract והציבו את `heb.traineddata` בתיקיית `tessdata`
שבשורש הפרויקט (או הגדירו `TESSDATA_DIR`), והתקינו `pip install pytesseract`.

## בניית EXE

```bash
pip install pyinstaller
pyinstaller hebrew_search.spec --noconfirm --clean
```

התוצר: `dist\HebrewSearch.exe` — קובץ יחיד ועצמאי.

## היכן נשמרים הנתונים

`%LOCALAPPDATA%\HebrewSearch` — אינדקס, קטלוג (SQLite) ולוגים. ניתן לעקוף
דרך משתנה הסביבה `HEBREW_SEARCH_DATA`.

## ארכיטקטורה

- `backend/` — FastAPI, מנוע Tantivy, חילוץ, OCR, נירמול עברי, מעקב קבצים.
- `frontend/` — React‏ (Vite), ממשק RTL, מוגש כקבצים סטטיים מתוך ה-backend.
- `main.py` — משגר: מריץ את השרת בתהליך רקע ופותח חלון pywebview.
- `_devtest/` — בדיקות עשן (רצות גם ב-CI).

## גרסאות ושחרורים

הפרויקט מתנהל לפי [SemVer](https://semver.org/lang/he/); השינויים מתועדים
ב-[CHANGELOG.md](CHANGELOG.md). דחיפת תג `vX.Y.Z` מפעילה ב-GitHub Actions
בנייה אוטומטית של `HebrewSearch.exe` וצירופו ל-Release.

## תרומה

ראו [CONTRIBUTING.md](CONTRIBUTING.md). דיווחי באגים ובקשות פיצ'רים —
דרך Issues.

## רישיון

הקוד ברישיון [MIT](LICENSE). הפרויקט מצרף גופני Frank Ruehl CLM מפרויקט
[Culmus](https://culmus.sourceforge.io) (רישיון GPL-2) ומודלי שפה של
Tesseract (רישיון Apache-2.0) — פירוט בקובץ LICENSE.
