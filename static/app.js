const HELP = {
  original: "", ela: "Zones claires = se recompressent différemment. Un collage ressort souvent en plus clair.",
  noise: "Rouge vif = bruit élevé. Un objet ajouté a souvent un bruit différent de son entourage.",
  spectrum: "Des points brillants réguliers hors du centre trahissent un suréchantillonnage (IA) ou une trame.",
  copymove: "Les lignes relient des zones identiques à différents endroits de l'image.",
};
const ICON = { fake: "!", warn: "?", ok: "✓", info: "i" };
let res = null, layer = "original";

const drop = $("#drop"), file = $("#file");
drop.onclick = () => file.click();
file.onchange = () => file.files[0] && run(file.files[0]);
["dragenter", "dragover"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(e => drop.addEventListener(e, ev => { ev.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", ev => ev.dataTransfer.files[0] && run(ev.dataTransfer.files[0]));
$$("#tabs .tab").forEach(t => t.onclick = () => { $$("#tabs .tab").forEach(x => x.classList.remove("on")); t.classList.add("on"); layer = t.dataset.l; show(); });
$("#op").oninput = e => $("#layer").style.opacity = e.target.value;

async function run(blob) {
  $("#orig").src = URL.createObjectURL(blob); $("#orig").hidden = false; $("#ph").hidden = true;
  $("#signals").innerHTML = `<div class="item muted">Analyse en cours…</div>`;
  const fd = new FormData(); fd.append("image", blob, blob.name || "image.jpg");
  try { res = await api("/api/analyze", { method: "POST", body: fd }); render(); }
  catch (e) { $("#signals").innerHTML = ""; toast("Erreur : " + e.message); }
}
function render() {
  $("#verdictCard").hidden = false; $("#score").textContent = res.score; $("#verdict").textContent = res.verdict;
  $("#verdict").style.color = res.score < 35 ? "var(--ok)" : res.score < 60 ? "var(--warn)" : "var(--red2)";
  $("#arc").style.strokeDashoffset = 267 * (1 - res.score / 100);
  $("#signals").innerHTML = res.signals.map(s => `<div class="sig"><span class="ic ${s.level}">${ICON[s.level]}</span><span>${esc(s.msg)}</span></div>`).join("")
    || `<div class="item muted">Aucun indice particulier.</div>`;
  const m = res.meta, rows = [["Format", m.format], ["Dimensions", m.taille], ["Mode", m.mode]];
  if (m["qualité JPEG estimée"] != null) rows.push(["Qualité JPEG", m["qualité JPEG estimée"]]);
  Object.entries(m.exif || {}).slice(0, 18).forEach(([k, v]) => rows.push([k, v]));
  Object.entries(m.chunks || {}).slice(0, 6).forEach(([k, v]) => rows.push([`[${k}]`, v]));
  if (!Object.keys(m.exif || {}).length) rows.push(["EXIF", "aucune"]);
  $("#meta").innerHTML = rows.map(([k, v]) => `<div>${esc(k)}</div><div>${esc(v)}</div>`).join("");
  const labels = { ela_ratio: "Ratio ELA", noise_cv: "Variabilité du bruit", fft_peaks: "Pics spectraux", copy_move_pairs: "Paires copier-coller" };
  $("#metrics").innerHTML = Object.entries(res.metrics).map(([k, v]) => `<div>${labels[k]}</div><div class="mono">${v}</div>`).join("");
  show();
}
function show() {
  $("#layerHelp").textContent = HELP[layer];
  const L = $("#layer");
  if (!res || layer === "original") { L.hidden = true; return; }
  L.src = res.layers[layer]; L.hidden = false; L.style.opacity = $("#op").value;
  const o = $("#orig"); L.style.width = o.clientWidth + "px"; L.style.height = o.clientHeight + "px";
}
addEventListener("resize", show);

// Démo : dessine une scène, duplique une zone (copier-coller) puis colle un élément recompressé.
$("#demo").onclick = () => {
  const c = document.createElement("canvas"); c.width = 960; c.height = 600; const x = c.getContext("2d");
  const g = x.createLinearGradient(0, 0, 0, 600); g.addColorStop(0, "#1d2b44"); g.addColorStop(.6, "#d9774b"); g.addColorStop(1, "#2a1a14"); x.fillStyle = g; x.fillRect(0, 0, 960, 600);
  const id = x.getImageData(0, 0, 960, 600); for (let i = 0; i < id.data.length; i += 4) { const n = (Math.random() - .5) * 26; id.data[i] += n; id.data[i + 1] += n; id.data[i + 2] += n; } x.putImageData(id, 0, 0);
  for (let i = 0; i < 40; i++) { x.fillStyle = `hsl(${20 + Math.random() * 30},40%,${10 + Math.random() * 20}%)`; x.fillRect(Math.random() * 960, 380 + Math.random() * 220, 20 + Math.random() * 60, -Math.random() * 160); }
  x.fillStyle = "#f4e3a1"; x.beginPath(); x.arc(250, 200, 50, 0, 7); x.fill();
  x.drawImage(c, 120, 360, 200, 220, 640, 360, 200, 220); // zone dupliquée
  x.fillStyle = "#fff"; x.font = "bold 46px sans-serif"; x.fillText("SCOOP", 700, 120); // élément « collé » propre, sans bruit
  c.toBlob(b => { b.name = "demo-piegee.jpg"; run(b); }, "image/jpeg", .85);
};
