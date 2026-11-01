from pathlib import Path

p = Path(r"D:\EduFlow\frontend\src\views\ProfileView.vue")
t = p.read_text(encoding="utf-8")

if "async function loadPoints" not in t:
    func = '''async function loadPoints() {
  if (!auth.isStudent) return
  try {
    myPoints.value = await api.get('/api/my/points')
  } catch {
    myPoints.value = null
  }
}

'''
    t = t.replace("function startEdit() {", func + "function startEdit() {", 1)
    p.write_text(t, encoding="utf-8")
    print("已补 loadPoints")
else:
    print("已存在")
