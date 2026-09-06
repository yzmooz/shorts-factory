const $ = (id) => document.getElementById(id),
  clone = (v) => structuredClone(v);
const C = { ally: "#65f1c2", enemy: "#ff6b76", gold: "#ffd78b" };
const map = $("map"),
  ctx = map.getContext("2d"),
  preview = $("preview"),
  pv = preview.getContext("2d");
const surface = document.createElement("canvas");
surface.width = 1008;
surface.height = 980;
const sc = surface.getContext("2d");
let story,
  index = 0,
  selected = null,
  tool = "select",
  hero = "ursa",
  team = "ally",
  time = 0,
  playing = false,
  playAll = false;
let templateId = null,
  history = [],
  future = [],
  drag = null,
  last = 0,
  dirty = true,
  job = null;
const images = {},
  heroes = {};
const toolDefs = [
  ["select", "↖", "Выбрать"],
  ["pan", "✥", "Двигать карту"],
  ["arrow", "↗", "Стрелка"],
  ["draw", "〰", "Карандаш"],
  ["zone", "◯", "Зона обзора"],
  ["fog", "◉", "Туман"],
  ["ward", "⊙", "Вард"],
  ["ability", "✦", "Способность"],
  ["text", "T", "Подпись"],
];
const scene = () => story.scenes[index],
  obj = () => scene().objects.find((o) => o.id === selected);
const uid = () => crypto.randomUUID();
function toast(text) {
  $("toast").textContent = text;
  $("toast").classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $("toast").classList.remove("show"), 2500);
}
function checkpoint() {
  history.push(JSON.stringify(story));
  if (history.length > 70) history.shift();
  future = [];
  $("saved").textContent = "Есть изменения";
  dirty = true;
}
function changed() {
  dirty = true;
  $("saved").textContent = "Есть изменения";
}
async function request(url, data) {
  const res = await fetch(
    url,
    data
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        }
      : {},
  );
  const result = await res.json();
  if (!res.ok) throw Error(result.error || "Ошибка запроса");
  return result;
}
function button(text, fn) {
  const b = document.createElement("button");
  b.textContent = text;
  b.onclick = fn;
  return b;
}
function setTool(next) {
  tool = next;
  document
    .querySelectorAll("[data-tool]")
    .forEach((b) => b.classList.toggle("active", b.dataset.tool === tool));
  document
    .querySelectorAll(".hero")
    .forEach((b) =>
      b.classList.toggle("active", tool === "hero" && b.dataset.hero === hero),
    );
  $("tip").textContent = {
    select: "Перетащи объект. Delete — удалить. Ctrl+Z — отменить.",
    pan: "Перетащи карту. Колесо мыши — масштаб.",
    arrow: "Проведи стрелку по карте.",
    draw: "Рисуй мышью. Линия появится по ходу сцены.",
    zone: "Протяни от центра до края зоны.",
    fog: "Протяни, чтобы скрыть участок карты.",
    ward: "Кликни, чтобы поставить вард.",
    ability: "Протяни от героя к цели: AoE, снаряд, Blink, контроль или урон.",
    text: "Кликни на карту и впиши подпись справа.",
    hero: "Кликни на карту или перетащи портрет героя.",
    route: "Проведи маршрут от героя к конечной точке.",
  }[tool];
}
function stop() {
  playing = false;
  playAll = false;
  $("play").textContent = "▶";
}
function loadStory(data, id = null) {
  story = clone(data);
  index = 0;
  selected = null;
  templateId = id;
  history = [];
  future = [];
  time = 0;
  stop();
  refresh();
  $("saved").textContent = id
    ? "Шаблон загружен"
    : "Пример · можно редактировать";
}
function refresh() {
  index = Math.min(index, story.scenes.length - 1);
  $("title").value = story.title;
  $("scene-name").textContent = scene().headline;
  $("headline").value = scene().headline;
  $("caption").value = scene().caption;
  $("narration").value = scene().narration;
  $("duration").value = scene().duration;
  $("zoom-label").value = scene().camera.zoom.toFixed(1) + "×";
  timeline();
  properties();
  dirty = true;
}
function timeline() {
  const el = $("timeline");
  el.replaceChildren();
  story.scenes.forEach((s, i) => {
    const b = button("", () => {
      stop();
      index = i;
      time = 0;
      selected = null;
      refresh();
    });
    b.className = "scene-card" + (i === index ? " active" : "");
    const n = document.createElement("small");
    n.textContent = `${String(i + 1).padStart(2, "0")} / ${Number(s.duration).toFixed(1)} сек`;
    const title = document.createElement("strong");
    title.textContent = s.headline;
    b.append(n, title);
    el.append(b);
  });
}
function properties() {
  const o = obj();
  $("object-panel").hidden = !o;
  if (!o) return;
  $("object-text").value = o.text || "";
  $("object-text").parentElement.hidden = !["text", "ability"].includes(o.type);
  $("ability-panel").hidden = o.type !== "ability";
  if (o.type === "ability") {
    $("ability-name").value = o.ability || "ABILITY";
    $("ability-effect").value = o.effect || "aoe";
    $("ability-value").value = o.value || "";
  }
  $("object-hidden").parentElement.hidden = o.type !== "hero";
  $("object-hidden").checked = !!o.hidden;
  $("route").hidden = o.type !== "hero";
  $("object-color").value = o.color || o.team || "ally";
}
function box() {
  const c = scene().camera,
    z = c.zoom * (1 + 0.025 * time),
    cw = 1 / z,
    ch = (((cw * 980) / 1008) * images.terrain.width) / images.terrain.height;
  return { x: c.x - cw / 2, y: c.y - ch / 2, w: cw, h: ch };
}
function toMap(event) {
  const r = map.getBoundingClientRect(),
    b = box();
  return [
    Math.max(0, Math.min(1, b.x + ((event.clientX - r.left) / r.width) * b.w)),
    Math.max(0, Math.min(1, b.y + ((event.clientY - r.top) / r.height) * b.h)),
  ];
}
function point(p, b = box()) {
  return [((p[0] - b.x) / b.w) * 1008, ((p[1] - b.y) / b.h) * 980];
}
function lerp(points, t) {
  if (!points?.length) return [0, 0];
  if (points.length === 1) return points[0];
  const ds = points
    .slice(1)
    .map((p, i) => Math.hypot(p[0] - points[i][0], p[1] - points[i][1]));
  let remaining = Math.max(0, Math.min(1, t)) * ds.reduce((a, b) => a + b, 0);
  for (let i = 0; i < ds.length; i++) {
    if (ds[i] && remaining <= ds[i])
      return points[i].map(
        (v, k) => v + ((points[i + 1][k] - v) * remaining) / ds[i],
      );
    remaining -= ds[i];
  }
  return points.at(-1);
}
function round(g, x, y, w, h, r, fill, stroke) {
  g.beginPath();
  g.roundRect(x, y, w, h, r);
  if (fill) {
    g.fillStyle = fill;
    g.fill();
  }
  if (stroke) {
    g.strokeStyle = stroke;
    g.stroke();
  }
}
function circle(g, x, y, r, fill, stroke, width = 2) {
  g.beginPath();
  g.arc(x, y, r, 0, Math.PI * 2);
  if (fill) {
    g.fillStyle = fill;
    g.fill();
  }
  if (stroke) {
    g.lineWidth = width;
    g.strokeStyle = stroke;
    g.stroke();
  }
}
function text(g, str, x, y, size, color = "#fff", max = 1000, maxLines = 3) {
  g.font = `700 ${size}px Arial`;
  const words = str.split(/\s+/);
  let lines = [],
    line = "";
  for (const word of words) {
    const next = (line + " " + word).trim();
    if (g.measureText(next).width > max && line) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  if (lines.length > maxLines && size > 20)
    return text(g, str, x, y, size - 3, color, max, maxLines);
  g.fillStyle = color;
  g.textBaseline = "top";
  lines
    .slice(0, maxLines)
    .forEach((l, i) => g.fillText(l, x, y + i * size * 1.16));
}
function linePoints(points, t) {
  if (t >= 1) return points;
  let lens = points
      .slice(1)
      .map((p, i) => Math.hypot(p[0] - points[i][0], p[1] - points[i][1])),
    distance = lens.reduce((a, b) => a + b, 0) * t,
    result = [points[0]];
  for (let i = 0; i < lens.length; i++) {
    if (distance >= lens[i]) {
      result.push(points[i + 1]);
      distance -= lens[i];
    } else {
      result.push(
        lerp([points[i], points[i + 1]], distance / Math.max(0.001, lens[i])),
      );
      break;
    }
  }
  return result;
}
function paintMap(g) {
  const ordered = [...scene().objects].sort((a, b) =>
    ({ arrow: 0, draw: 0, ability: 1, hero: 2, text: 3 }[a.type] ?? 2) -
    ({ arrow: 0, draw: 0, ability: 1, hero: 2, text: 3 }[b.type] ?? 2),
  );
  const b = box();
  g.clearRect(0, 0, 1008, 980);
  g.fillStyle = "#090f17";
  g.fillRect(0, 0, 1008, 980);
  g.drawImage(
    images.terrain,
    b.x * images.terrain.width,
    b.y * images.terrain.height,
    b.w * images.terrain.width,
    b.h * images.terrain.height,
    0,
    0,
    1008,
    980,
  );
  g.fillStyle = "#06101b18";
  g.fillRect(0, 0, 1008, 980);
  for (const o of ordered) {
    if (!["zone", "fog"].includes(o.type)) continue;
    const [x, y] = point([o.x, o.y], b),
      r = ((o.radius || 0.06) / b.w) * 1008,
      col = C[o.color || "gold"];
    if (o.type === "fog") {
      const grad = g.createRadialGradient(x, y, r * 0.45, x, y, r);
      grad.addColorStop(0, "#030b16ef");
      grad.addColorStop(0.7, "#030b16c9");
      grad.addColorStop(1, "#030b1600");
      circle(g, x, y, r, grad);
    } else {
      circle(g, x, y, r, col + "24", col + "99", 3);
      circle(
        g,
        x,
        y,
        r * (0.83 + 0.17 * ((time * 2) % 1)),
        null,
        col + "60",
        2,
      );
    }
  }
  for (const o of ordered) {
    const col = C[o.color || o.team || "ally"];
    if (["arrow", "draw"].includes(o.type) && o.points?.length > 1) {
      const pts = linePoints(
        o.points.map((p) => point(p, b)),
        o.reveal ? Math.min(1, time * 1.9 + 0.04) : 1,
      );
      g.lineCap = "round";
      g.lineJoin = "round";
      g.beginPath();
      pts.forEach((p, i) => (i ? g.lineTo(...p) : g.moveTo(...p)));
      g.lineWidth = 16;
      g.strokeStyle = "#071018c0";
      g.stroke();
      g.lineWidth = 7;
      g.strokeStyle = col;
      g.shadowColor = col;
      g.shadowBlur = 10;
      g.stroke();
      g.shadowBlur = 0;
      if (o.type === "arrow") {
        const a = pts.at(-2),
          v = pts.at(-1),
          angle = Math.atan2(v[1] - a[1], v[0] - a[0]);
        g.beginPath();
        g.moveTo(...v);
        g.lineTo(
          v[0] - 29 * Math.cos(angle - 0.5),
          v[1] - 29 * Math.sin(angle - 0.5),
        );
        g.lineTo(
          v[0] - 29 * Math.cos(angle + 0.5),
          v[1] - 29 * Math.sin(angle + 0.5),
        );
        g.closePath();
        g.fillStyle = col;
        g.fill();
      }
    } else if (o.type === "hero") {
      const position = lerp(
          o.path || [[o.x, o.y]],
          time * time * (3 - 2 * time),
        ),
        [x, y] = point(position, b);
      g.shadowColor = col;
      g.shadowBlur = 20;
      circle(g, x, y, 53, "#08131a", col, 5);
      g.shadowBlur = 0;
      if (o.hidden) {
        text(g, "?", x - 17, y - 30, 55, col);
      } else {
        const im = images[o.asset];
        g.save();
        circle(g, x, y, 45);
        g.clip();
        const side = Math.min(im.width, im.height);
        g.drawImage(
          im,
          (im.width - side) / 2,
          0,
          side,
          side,
          x - 45,
          y - 45,
          90,
          90,
        );
        g.restore();
      }
      round(g, x - 38, y + 56, 76, 6, 3, col);
    } else if (o.type === "ward") {
      const [x, y] = point([o.x, o.y], b);
      circle(g, x, y, 38, "#101b1e", C.gold, 3);
      g.drawImage(images.observer, x - 31, y - 23, 62, 46);
    } else if (o.type === "ability") {
      const abilityColors = {
          aoe: "#ffb454",
          projectile: "#8bd5ff",
          blink: "#d49bff",
          control: "#ff6b76",
          damage: "#ffdb6e",
        },
        effect = o.effect || "aoe",
        ac = abilityColors[effect] || abilityColors.aoe,
        origin = point([o.x, o.y], b),
        target = point(o.target || [o.x, o.y], b),
        progress = o.reveal === false ? 1 : Math.min(1, time * 1.55 + 0.04),
        current = [
          origin[0] + (target[0] - origin[0]) * progress,
          origin[1] + (target[1] - origin[1]) * progress,
        ],
        radius = ((o.radius || 0.055) / b.w) * 1008;
      g.save();
      g.shadowColor = ac;
      g.shadowBlur = 16;
      if (effect === "projectile") {
        g.lineWidth = 14;
        g.strokeStyle = "#050b11dd";
        g.beginPath();
        g.moveTo(...origin);
        g.lineTo(...current);
        g.stroke();
        g.lineWidth = 7;
        g.strokeStyle = ac;
        g.beginPath();
        g.moveTo(...origin);
        g.lineTo(...current);
        g.stroke();
        circle(g, current[0], current[1], 14, ac, "#fff", 2);
      } else if (effect === "blink") {
        g.setLineDash([18, 12]);
        g.lineWidth = 6;
        g.strokeStyle = ac;
        g.beginPath();
        g.moveTo(...origin);
        g.lineTo(...target);
        g.stroke();
        g.setLineDash([]);
        circle(g, current[0], current[1], radius * 0.65, ac + "34", ac, 5);
        circle(g, current[0], current[1], radius * 0.3, ac + "80");
      } else if (effect === "control") {
        circle(g, target[0], target[1], radius, ac + "26", ac, 6);
        for (let i = 0; i < 8; i++) {
          const a = (i * Math.PI) / 4;
          g.beginPath();
          g.moveTo(
            target[0] + Math.cos(a) * radius * 0.72,
            target[1] + Math.sin(a) * radius * 0.72,
          );
          g.lineTo(
            target[0] + Math.cos(a) * radius * 1.15,
            target[1] + Math.sin(a) * radius * 1.15,
          );
          g.strokeStyle = ac;
          g.lineWidth = 5;
          g.stroke();
        }
      } else {
        const pulse = radius * (0.82 + 0.18 * ((time * 2.2) % 1));
        circle(g, target[0], target[1], pulse, ac + "30", ac, 5);
        if (effect === "damage") {
          for (let i = 0; i < 8; i++) {
            const a = (i * Math.PI) / 4;
            g.beginPath();
            g.moveTo(
              target[0] + Math.cos(a) * pulse * 0.8,
              target[1] + Math.sin(a) * pulse * 0.8,
            );
            g.lineTo(
              target[0] + Math.cos(a) * pulse * 1.35,
              target[1] + Math.sin(a) * pulse * 1.35,
            );
            g.strokeStyle = ac;
            g.lineWidth = 5;
            g.stroke();
          }
        }
      }
      g.shadowBlur = 0;
      const caster = images[o.caster];
      if (caster) {
        g.save();
        circle(g, origin[0], origin[1], 28, "#071018", ac, 3);
        g.clip();
        g.drawImage(caster, origin[0] - 24, origin[1] - 24, 48, 48);
        g.restore();
      }
      const label =
        String(o.ability || "ABILITY").toUpperCase() +
        (o.value ? " · " + o.value : "");
      g.font = "700 22px Arial";
      const w = g.measureText(label).width;
      const lx = Math.max(w / 2 + 12, Math.min(996 - w / 2, target[0])),
        ly = Math.max(8, target[1] - radius - 34);
      round(g, lx - w / 2 - 10, ly - 5, w + 20, 34, 9, "#050b11e8", ac);
      text(g, label, lx - w / 2, ly, 22, ac, 960, 1);
      g.restore();
    } else if (o.type === "text") {
      let [x, y] = point([o.x, o.y], b);
      g.font = "700 29px Arial";
      const w = g.measureText(o.text || "Подпись").width;
      x = Math.max(w / 2 + 14, Math.min(994 - w / 2, x));
      y = Math.max(8, Math.min(930, y));
      g.lineWidth = 2;
      round(g, x - w / 2 - 12, y - 7, w + 24, 43, 10, "#0a1723ed", col);
      text(g, o.text || "Подпись", x - w / 2, y, 29, col);
    }
  }
  g.fillStyle = "#f4e8cf";
  g.shadowColor = "#000";
  g.shadowBlur = 5;
  g.font = "700 21px Arial";
  g.textBaseline = "top";
  g.fillText("УЧЕБНАЯ СИТУАЦИЯ", 20, 20);
  g.shadowBlur = 0;
}
function paint() {
  paintMap(sc);
  ctx.clearRect(0, 0, 1008, 980);
  ctx.drawImage(surface, 0, 0);
  const o = obj();
  if (o) {
    const p =
      o.type === "hero"
        ? lerp(o.path || [[o.x, o.y]], time * time * (3 - 2 * time))
        : [o.x ?? o.points?.[0]?.[0], o.y ?? o.points?.[0]?.[1]];
    const [x, y] = point(p);
    ctx.save();
    ctx.setLineDash([6, 7]);
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#fff";
    ctx.strokeRect(x - 62, y - 62, 124, 124);
    ctx.restore();
  }
  pv.fillStyle = "#080f17";
  pv.fillRect(0, 0, 1080, 1920);
  round(pv, 45, 56, 14, 29, 5, C.ally);
  text(pv, "DOTA / РАЗБОР МОМЕНТА", 77, 55, 26, "#a8bfce");
  text(pv, scene().headline, 45, 118, 78, "#f1f5f6", 980, 2);
  pv.save();
  pv.beginPath();
  pv.roundRect(36, 290, 1008, 980, 28);
  pv.clip();
  pv.drawImage(surface, 36, 290);
  pv.restore();
  pv.lineWidth = 2;
  round(pv, 36, 290, 1008, 980, 28, null, "#344554");
  text(pv, "●  ТВОЯ КОМАНДА", 48, 1302, 22, C.ally);
  text(pv, "●  ПРОТИВНИК", 378, 1302, 22, C.enemy);
  text(pv, "КАРТА 7.40", 765, 1302, 22, "#758d9f");
  text(pv, scene().caption, 48, 1380, 48, C.ally, 980, 2);
  text(pv, scene().narration, 48, 1510, 35, "#b7c7d3", 960, 3);
  const w = 420,
    h = (images.brand.height / images.brand.width) * w;
  pv.drawImage(images.brand, 330, 1700, w, h);
  $("time").value =
    `${(time * scene().duration).toFixed(1)} / ${Number(scene().duration).toFixed(1)} сек`;
  $("scrub").value = Math.round(time * 1000);
  dirty = false;
}
function animate(ts) {
  if (story && images.terrain && images.brand) {
    if (playing) {
      time += (ts - last) / 1000 / scene().duration;
      if (time >= 1) {
        if (playAll && index < story.scenes.length - 1) {
          index++;
          time = 0;
          selected = null;
          refresh();
        } else {
          time = 1;
          stop();
        }
      }
      dirty = true;
    }
    if (dirty) paint();
  }
  last = ts;
  requestAnimationFrame(animate);
}
function hit(p) {
  const b = box(),
    r = 0.022 * b.w * 2.5;
  return [...scene().objects].reverse().find((o) => {
    if (o.type === "hero") {
      const q = lerp(o.path || [[o.x, o.y]], time * time * (3 - 2 * time));
      return Math.hypot(q[0] - p[0], q[1] - p[1]) < r;
    }
    if (o.points) {
      return o.points.some((q) => Math.hypot(q[0] - p[0], q[1] - p[1]) < r);
    }
    if (o.type === "ability" && o.target) {
      return (
        Math.hypot(o.x - p[0], o.y - p[1]) < r ||
        Math.hypot(o.target[0] - p[0], o.target[1] - p[1]) < r
      );
    }
    return (
      Math.hypot(o.x - p[0], o.y - p[1]) <
      (o.type === "zone" || o.type === "fog" ? o.radius : r)
    );
  });
}
map.onpointerdown = (e) => {
  if (e.button !== 0 && e.button !== 1) return;
  stop();
  const p = toMap(e);
  map.setPointerCapture(e.pointerId);
  if (tool === "pan" || e.button === 1) {
    checkpoint();
    drag = {
      type: "pan",
      screen: [e.clientX, e.clientY],
      camera: clone(scene().camera),
    };
    return;
  }
  if (tool === "select") {
    const found = hit(p);
    selected = found?.id || null;
    properties();
    dirty = true;
    if (found) {
      checkpoint();
      drag = { type: "move", origin: p, object: clone(found) };
    }
    return;
  }
  if (tool === "route") {
    const o = obj();
    if (o?.type === "hero") {
      checkpoint();
      o.path = [[o.x, o.y], p];
      drag = { type: "route", id: o.id };
    }
    return;
  }
  checkpoint();
  let o = { id: uid(), type: tool, x: p[0], y: p[1], color: team };
  if (tool === "hero") o = { ...o, asset: hero, team, path: [p, p] };
  if (tool === "ward") o.color = "gold";
  if (tool === "text") o.text = "Подпись";
  if (tool === "ability") {
    o = {
      ...o,
      ability: "ABILITY",
      caster: hero,
      effect: "aoe",
      target: [p[0], p[1]],
      radius: 0.055,
      value: "",
      reveal: true,
    };
  }
  if (tool === "zone" || tool === "fog") {
    o.radius = 0.01;
    o.color = tool === "zone" ? "gold" : "enemy";
  }
  if (tool === "arrow" || tool === "draw") {
    o.points = [p, p];
    o.reveal = true;
    delete o.x;
    delete o.y;
  }
  scene().objects.push(o);
  selected = o.id;
  drag = { type: "create", id: o.id, origin: p };
  properties();
  dirty = true;
};
map.onpointermove = (e) => {
  if (!drag) return;
  const p = toMap(e),
    o = obj();
  if (drag.type === "pan") {
    const rect = map.getBoundingClientRect(),
      cam = scene().camera;
    cam.x = Math.max(
      0,
      Math.min(
        1,
        drag.camera.x -
          (e.clientX - drag.screen[0]) / rect.width / drag.camera.zoom,
      ),
    );
    cam.y = Math.max(
      0,
      Math.min(
        1,
        drag.camera.y -
          (((((e.clientY - drag.screen[1]) / rect.height / drag.camera.zoom) *
            980) /
            1008) *
            images.terrain.width) /
            images.terrain.height,
      ),
    );
  } else if (drag.type === "move" && o) {
    const dx = p[0] - drag.origin[0],
      dy = p[1] - drag.origin[1],
      clamp = (v) => Math.max(0, Math.min(1, v));
    if (drag.object.x !== undefined) {
      o.x = clamp(drag.object.x + dx);
      o.y = clamp(drag.object.y + dy);
    }
    for (const field of ["points", "path"])
      if (drag.object[field])
        o[field] = drag.object[field].map((q) => [
          clamp(q[0] + dx),
          clamp(q[1] + dy),
        ]);
    if (drag.object.target)
      o.target = [clamp(drag.object.target[0] + dx), clamp(drag.object.target[1] + dy)];
  } else if (drag.type === "route" && o) {
    if (Math.hypot(p[0] - o.path.at(-1)[0], p[1] - o.path.at(-1)[1]) > 0.002)
      o.path.push(p);
  } else if (drag.type === "create" && o) {
    if (o.type === "zone" || o.type === "fog")
      o.radius = Math.min(
        0.5,
        Math.max(
          0.004,
          Math.hypot(p[0] - drag.origin[0], p[1] - drag.origin[1]),
        ),
      );
    if (o.points) {
      if (o.type === "draw") {
        if (
          Math.hypot(p[0] - o.points.at(-1)[0], p[1] - o.points.at(-1)[1]) >
          0.001
        )
          o.points.push(p);
      } else o.points[1] = p;
    }
    if (o.type === "ability") o.target = p;
  }
  dirty = true;
};
map.onpointerup = () => {
  if (drag?.type === "route") setTool("select");
  if (drag && obj()?.type === "text") {
    $("object-text").focus();
    $("object-text").select();
  }
  drag = null;
  changed();
};
map.onwheel = (e) => {
  e.preventDefault();
  checkpoint();
  scene().camera.zoom = Math.min(
    6,
    Math.max(1, scene().camera.zoom * (e.deltaY < 0 ? 1.07 : 1 / 1.07)),
  );
  $("zoom-label").value = scene().camera.zoom.toFixed(1) + "×";
  dirty = true;
};
map.ondragover = (e) => e.preventDefault();
map.ondrop = (e) => {
  e.preventDefault();
  const slug = e.dataTransfer.getData("text/plain");
  if (!heroes[slug]) return;
  checkpoint();
  const p = toMap(e);
  const o = {
    id: uid(),
    type: "hero",
    asset: slug,
    x: p[0],
    y: p[1],
    path: [p, p],
    team,
  };
  scene().objects.push(o);
  selected = o.id;
  properties();
  changed();
};
for (const [name, icon, label] of toolDefs) {
  const b = button("", () => setTool(name));
  b.dataset.tool = name;
  const s = document.createElement("span");
  s.textContent = icon;
  b.append(s, document.createTextNode(label));
  $("tools").append(b);
}
setTool("select");
document.querySelectorAll("[data-team]").forEach(
  (b) =>
    (b.onclick = () => {
      team = b.dataset.team;
      document
        .querySelectorAll("[data-team]")
        .forEach((x) => x.classList.toggle("active", x === b));
    }),
);
for (const field of ["headline", "caption", "narration", "duration"]) {
  $(field).onfocus = () => checkpoint();
  $(field).oninput = () => {
    scene()[field] =
      field === "duration"
        ? Math.min(30, Math.max(0.5, Number($(field).value) || 0.5))
        : $(field).value;
    changed();
    $("scene-name").textContent = scene().headline;
    timeline();
  };
}
$("title").onfocus = () => checkpoint();
$("title").oninput = () => {
  story.title = $("title").value;
  changed();
};
$("object-text").onfocus = () => checkpoint();
$("object-text").oninput = () => {
  if (obj()) {
    obj().text = $("object-text").value;
    changed();
  }
};
for (const field of ["ability-name", "ability-value"]) {
  $(field).onfocus = () => checkpoint();
  $(field).oninput = () => {
    if (obj()?.type === "ability") {
      if (field === "ability-name") obj().ability = $(field).value;
      else obj().value = $(field).value;
      changed();
    }
  };
}
$("ability-effect").onchange = () => {
  if (obj()?.type === "ability") {
    checkpoint();
    obj().effect = $("ability-effect").value;
    changed();
  }
};
$("object-color").onchange = () => {
  if (obj()) {
    checkpoint();
    if (obj().type === "hero") obj().team = $("object-color").value;
    else obj().color = $("object-color").value;
    changed();
  }
};
$("object-hidden").onchange = () => {
  if (obj()) {
    checkpoint();
    obj().hidden = $("object-hidden").checked;
    changed();
  }
};
$("route").onclick = () => {
  time = 0;
  setTool("route");
  dirty = true;
};
function removeObject() {
  if (!obj()) return;
  checkpoint();
  scene().objects = scene().objects.filter((o) => o.id !== selected);
  selected = null;
  properties();
  changed();
}
$("delete-object").onclick = removeObject;
$("undo").onclick = () => {
  if (!history.length) return;
  future.push(JSON.stringify(story));
  story = JSON.parse(history.pop());
  index = Math.min(index, story.scenes.length - 1);
  selected = null;
  time = 0;
  refresh();
};
$("redo").onclick = () => {
  if (!future.length) return;
  history.push(JSON.stringify(story));
  story = JSON.parse(future.pop());
  selected = null;
  refresh();
};
$("zoom-in").onclick = () => {
  checkpoint();
  scene().camera.zoom = Math.min(6, scene().camera.zoom + 0.25);
  refresh();
};
$("zoom-out").onclick = () => {
  checkpoint();
  scene().camera.zoom = Math.max(1, scene().camera.zoom - 0.25);
  refresh();
};
$("play").onclick = () => {
  if (playing) {
    stop();
  } else {
    if (time >= 1) time = 0;
    playing = true;
    playAll = false;
    $("play").textContent = "Ⅱ";
  }
};
$("all").onclick = () => {
  index = 0;
  time = 0;
  playing = true;
  playAll = true;
  selected = null;
  refresh();
  $("play").textContent = "Ⅱ";
};
$("scrub").oninput = () => {
  stop();
  time = Number($("scrub").value) / 1000;
  dirty = true;
};
$("duplicate").onclick = () => {
  if (story.scenes.length >= 16) return toast("Максимум 16 сцен");
  checkpoint();
  const s = clone(scene());
  s.id = uid();
  s.objects.forEach((o) => (o.id = uid()));
  story.scenes.splice(index + 1, 0, s);
  index++;
  selected = null;
  time = 0;
  refresh();
};
$("add-scene").onclick = () => {
  if (story.scenes.length >= 16) return toast("Максимум 16 сцен");
  checkpoint();
  story.scenes.splice(index + 1, 0, {
    id: uid(),
    headline: "НОВЫЙ МОМЕНТ",
    caption: "Что происходит?",
    narration: "",
    duration: 4,
    camera: clone(scene().camera),
    objects: [],
  });
  index++;
  selected = null;
  time = 0;
  refresh();
};
$("delete-scene").onclick = () => {
  if (story.scenes.length === 1) return toast("Нужна хотя бы одна сцена");
  checkpoint();
  story.scenes.splice(index, 1);
  index = Math.min(index, story.scenes.length - 1);
  selected = null;
  time = 0;
  refresh();
};
async function listTemplates() {
  const list = await request("/api/templates");
  $("templates").replaceChildren(new Option("Выбрать шаблон…", ""));
  list.forEach((t) => $("templates").append(new Option(t.title, t.id)));
  if (templateId) $("templates").value = templateId;
}
$("save").onclick = async () => {
  try {
    const result = await request("/api/save", { story, id: templateId });
    templateId = result.id;
    $("saved").textContent = "Сохранено на этом ПК";
    await listTemplates();
    toast("Шаблон сохранён");
  } catch (e) {
    toast(e.message);
  }
};
$("templates").onchange = async () => {
  const id = $("templates").value;
  if (id)
    try {
      loadStory(await request("/api/templates/" + id), id);
    } catch (e) {
      toast(e.message);
    }
};
$("example").onclick = async () => loadStory(await request("/api/default"));
$("export").onclick = () => {
  const blob = new Blob([JSON.stringify(story, null, 2)], {
      type: "application/json",
    }),
    url = URL.createObjectURL(blob),
    a = document.createElement("a");
  a.href = url;
  a.download = "dota-map-template.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("JSON содержит все сцены, объекты и маршруты");
};
$("import").onclick = () => $("file").click();
$("file").onchange = async (e) => {
  try {
    const data = JSON.parse(await e.target.files[0].text());
    if (
      data.version !== 1 ||
      data.map !== "terrain-740.jpg" ||
      !data.scenes?.length
    )
      throw Error("Это не шаблон Map Studio");
    await request("/api/save", { story: data });
    loadStory(data);
    await listTemplates();
    toast("Шаблон импортирован");
  } catch (e) {
    toast(e.message);
  } finally {
    $("file").value = "";
  }
};
$("render").onclick = async () => {
  try {
    const result = await request("/api/render", { story });
    job = result.id;
    $("render").disabled = true;
    $("result").hidden = true;
    poll();
  } catch (e) {
    toast(e.message);
  }
};
async function poll() {
  try {
    const data = await request("/api/jobs/" + job);
    $("render-status").textContent = data.message;
    if (data.status === "running") setTimeout(poll, 1800);
    else {
      $("render").disabled = false;
      if (data.status === "done") {
        $("result").href = data.url;
        $("result").hidden = false;
        toast("Ролик готов на этом компьютере");
      }
    }
  } catch (e) {
    $("render-status").textContent = e.message;
    $("render").disabled = false;
  }
}
document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key.toLowerCase() === "s") {
    e.preventDefault();
    $("save").click();
    return;
  }
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName))
    return;
  if ((e.key === "Delete" || e.key === "Backspace") && obj()) {
    e.preventDefault();
    removeObject();
  }
  if (e.ctrlKey && e.key.toLowerCase() === "z") {
    e.preventDefault();
    $(e.shiftKey ? "redo" : "undo").click();
  }
  if (e.code === "Space") {
    e.preventDefault();
    $("play").click();
  }
});
async function loadImage(key, url) {
  images[key] = new Image();
  images[key].src = url;
  await images[key].decode();
}
async function init() {
  try {
    Object.assign(heroes, await request("/api/heroes"));
    await Promise.all([
      loadImage("terrain", "/assets/tactical/terrain-740.jpg"),
      loadImage("observer", "/assets/tactical/observer.png"),
      loadImage("brand", "/assets/ready-helper-banner.png"),
      ...Object.keys(heroes).map((h) =>
        loadImage(h, `/assets/tactical/${h}.png`),
      ),
    ]);
    for (const [slug, name] of Object.entries(heroes)) {
      const b = button("", () => {
        hero = slug;
        setTool("hero");
      });
      b.className = "hero";
      b.dataset.hero = slug;
      b.draggable = true;
      b.ondragstart = (e) => e.dataTransfer.setData("text/plain", slug);
      const im = document.createElement("img");
      im.src = `/assets/tactical/${slug}.png`;
      im.alt = "";
      b.append(im, document.createTextNode(name));
      $("heroes").append(b);
    }
    loadStory(await request("/api/default"));
    await listTemplates();
    $("loading").remove();
    requestAnimationFrame(animate);
  } catch (e) {
    $("loading").textContent = "Не удалось загрузить: " + e.message;
  }
}
init();
