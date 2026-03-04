from __future__ import annotations

import math
import random
import string
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

st.set_page_config(page_title="PlayPal", page_icon="🏆", layout="wide")

SPORT_ROLES: dict[str, list[str]] = {
    "Calcetto": ["Portiere", "Difensore", "Centrocampista", "Attaccante"],
    "Basket": ["Play", "Guardia", "Ala", "Centro"],
    "Padel": ["Sinistra", "Destra"],
    "Tennis": ["Singolarista", "Doppista"],
    "Pallavolo": ["Libero", "Palleggiatore", "Schiacciatore", "Centrale", "Opposto"],
    "Beach Volley": ["Difensore", "Attaccante"],
}

DEFAULT_REQUIRED_ROLES: dict[str, dict[str, int]] = {
    "Calcetto": {"Portiere": 1},
    "Basket": {"Play": 1, "Centro": 1},
    "Padel": {"Sinistra": 1, "Destra": 1},
    "Tennis": {"Singolarista": 1},
    "Pallavolo": {"Libero": 1, "Palleggiatore": 1},
    "Beach Volley": {"Difensore": 1, "Attaccante": 1},
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def generate_token(size: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(size))


def generate_code(size: int = 7) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(size))


def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371
    d_lat = math.radians(b_lat - a_lat)
    d_lon = math.radians(b_lon - a_lon)
    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    x = math.sin(d_lat / 2) ** 2 + math.sin(d_lon / 2) ** 2 * math.cos(lat1) * math.cos(lat2)
    return r * (2 * math.atan2(math.sqrt(x), math.sqrt(1 - x)))


def calc_reliability(matches_count: int, penalty: float = 0.0) -> float:
    baseline = min(1.0, 0.25 + matches_count / 40)
    return max(0.05, baseline - penalty)


def rating_delta(outcome: str, player_rating: float, opponent_rating: float, reliability: float, k_base: int = 40) -> int:
    expected = 1 / (1 + 10 ** ((opponent_rating - player_rating) / 400))
    score = 1.0 if outcome == "W" else 0.0
    reliability_mod = 1.6 - reliability
    delta = round(k_base * reliability_mod * (score - expected))
    return int(delta)


@dataclass
class User:
    username: str
    email: str
    password: str
    verified: bool = False
    reliability_penalty: float = 0.0
    last_reliability_reduce: datetime | None = None
    sports: list[str] = field(default_factory=list)
    roles_by_sport: dict[str, list[str]] = field(default_factory=dict)
    avatar: dict[str, str] = field(default_factory=lambda: {"hair": "Short", "color": "#F59E0B", "mood": "😄"})
    ratings: dict[str, int] = field(default_factory=dict)
    matches_registered: int = 0
    fair_play_votes: list[int] = field(default_factory=list)

    @property
    def reliability(self) -> float:
        return calc_reliability(self.matches_registered, self.reliability_penalty)


@dataclass
class MatchResult:
    submitted_by: str
    team_a_score: int
    team_b_score: int
    submitted_at: datetime
    confirmations: set[str] = field(default_factory=set)
    status: str = "pending"
    expires_at: datetime | None = None
    contested_by: str | None = None


if "db" not in st.session_state:
    st.session_state.db = {
        "users": {},
        "verification_tokens": {},
        "password_reset_tokens": {},
        "matches": {},
        "match_chat": {},
        "direct_chat": {},
        "rate_limit": {"signup": {}, "login": {}},
        "next_match_id": 1,
    }


db = st.session_state.db


st.title("🏆 PlayPal")
st.caption("Trova compagni di gioco, organizza partite e scala il ranking.")


def rate_limited(scope: str, key: str, max_attempts: int = 5, window_minutes: int = 10) -> bool:
    now = utc_now()
    bucket = db["rate_limit"][scope].setdefault(key, [])
    db["rate_limit"][scope][key] = [t for t in bucket if now - t < timedelta(minutes=window_minutes)]
    if len(db["rate_limit"][scope][key]) >= max_attempts:
        return True
    db["rate_limit"][scope][key].append(now)
    return False


with st.sidebar:
    st.subheader("Account")
    current = st.session_state.get("current_user")
    if current:
        st.success(f"Loggato come **{current}**")
        if st.button("Logout"):
            st.session_state.current_user = None
            st.rerun()
    else:
        mode = st.radio("Autenticazione", ["Login", "Signup", "Verifica email", "Reset password"], key="auth_mode")
        if mode == "Signup":
            user = st.text_input("Username")
            email = st.text_input("Email")
            pwd = st.text_input("Password", type="password")
            if st.button("Crea account"):
                if rate_limited("signup", email or user or "anon"):
                    st.error("Troppi tentativi signup. Riprova tra poco.")
                elif user in db["users"]:
                    st.error("Username già esistente.")
                else:
                    db["users"][user] = User(username=user, email=email, password=pwd)
                    token = generate_token(18)
                    db["verification_tokens"][token] = user
                    st.info(f"Email inviata (demo): token verifica `{token}`")
        if mode == "Verifica email":
            token = st.text_input("Token verifica")
            if st.button("Conferma email"):
                user = db["verification_tokens"].pop(token, None)
                if user:
                    db["users"][user].verified = True
                    st.success("Email verificata. Ora puoi effettuare login.")
                else:
                    st.error("Token non valido.")
        if mode == "Login":
            user = st.text_input("Username", key="login_user")
            pwd = st.text_input("Password", type="password", key="login_pwd")
            if st.button("Accedi"):
                if rate_limited("login", user or "anon"):
                    st.error("Troppi tentativi login. Riprova tra poco.")
                elif user in db["users"] and db["users"][user].password == pwd:
                    if not db["users"][user].verified:
                        st.warning("Devi verificare l'email prima di accedere.")
                    else:
                        st.session_state.current_user = user
                        st.rerun()
                else:
                    st.error("Credenziali non valide.")
        if mode == "Reset password":
            user = st.text_input("Username", key="reset_user")
            if st.button("Invia reset"):
                if user in db["users"]:
                    token = generate_token(16)
                    db["password_reset_tokens"][token] = user
                    st.info(f"Token reset (demo): `{token}`")
                else:
                    st.error("Utente non trovato.")
            token = st.text_input("Token reset")
            new_pwd = st.text_input("Nuova password", type="password")
            if st.button("Conferma reset"):
                owner = db["password_reset_tokens"].pop(token, None)
                if owner:
                    db["users"][owner].password = new_pwd
                    st.success("Password aggiornata.")
                else:
                    st.error("Token reset non valido.")


if not st.session_state.get("current_user"):
    st.info("Accedi o registrati per usare PlayPal.")
    st.stop()


user = db["users"][st.session_state.current_user]


tab_profile, tab_matches, tab_feed, tab_chat, tab_results, tab_ranking = st.tabs(
    ["Profilo", "Crea Match", "Bacheca", "Chat", "Risultati", "Ranking"]
)

with tab_profile:
    st.subheader("Profilo + Avatar + Sport + Ruoli")
    c1, c2 = st.columns([2, 1])
    with c1:
        sports = st.multiselect("Sport preferiti", list(SPORT_ROLES.keys()), default=user.sports)
        user.sports = sports
        for sport in sports:
            selected_roles = st.multiselect(
                f"Ruoli giocabili - {sport}",
                SPORT_ROLES[sport],
                default=user.roles_by_sport.get(sport, SPORT_ROLES[sport][:1]),
                key=f"roles_{sport}",
            )
            user.roles_by_sport[sport] = selected_roles
            user.ratings.setdefault(sport, 1000)
        if st.button("Salva profilo"):
            st.success("Profilo aggiornato.")
    with c2:
        st.write("**Avatar editor (demo)**")
        hair = st.selectbox("Hair", ["Short", "Long", "Curly", "Bald"], index=0)
        color = st.color_picker("Colore", value=user.avatar["color"])
        mood = st.selectbox("Mood", ["😄", "😎", "🤩", "🔥", "🧠"])
        user.avatar = {"hair": hair, "color": color, "mood": mood}
        st.markdown(
            f"<div style='padding:20px;border-radius:16px;background:{color};text-align:center;font-size:40px'>{mood}</div>",
            unsafe_allow_html=True,
        )
    fair_play = round(sum(user.fair_play_votes) / len(user.fair_play_votes), 2) if user.fair_play_votes else 0
    st.write(f"Affidabilità: **{user.reliability:.2f}** | Fair Play medio: **{fair_play}**")

with tab_matches:
    st.subheader("Crea partita")
    sport = st.selectbox("Sport", list(SPORT_ROLES.keys()))
    mode = st.selectbox("Modalità", ["singolo", "squadre"])
    team_size = st.number_input("Giocatori per team", min_value=1, max_value=11, value=1 if mode == "singolo" else 5)
    match_date = st.date_input("Data")
    start_time = st.time_input("Ora")
    duration = st.number_input("Durata (min)", min_value=15, value=60)
    city = st.text_input("Città")
    address = st.text_input("Indirizzo")
    lat = st.number_input("Latitudine", value=45.4642, format="%.4f")
    lon = st.number_input("Longitudine", value=9.1900, format="%.4f")
    competitive = st.toggle("Competitiva", value=True)
    visibility = st.selectbox("Visibilità", ["public", "private"])

    required = DEFAULT_REQUIRED_ROLES.get(sport, {})
    st.write("Ruoli obbligatori")
    custom_required: dict[str, int] = {}
    for role in SPORT_ROLES[sport]:
        qty = st.number_input(f"{role}", min_value=0, max_value=int(team_size), value=required.get(role, 0), key=f"req_{sport}_{role}")
        if qty:
            custom_required[role] = int(qty)

    if st.button("Pubblica partita"):
        match_id = db["next_match_id"]
        db["next_match_id"] += 1
        starts = datetime.combine(match_date, start_time).replace(tzinfo=timezone.utc)
        match = {
            "id": match_id,
            "creator": user.username,
            "sport": sport,
            "mode": mode,
            "team_size": int(team_size),
            "starts_at": starts,
            "duration": int(duration),
            "city": city,
            "address": address,
            "geo": (lat, lon),
            "competitive": competitive,
            "max_players": int(team_size * 2),
            "visibility": visibility,
            "status": "open",
            "required_roles": custom_required,
            "participants": [{"username": user.username, "team": "A", "role": None}],
            "invites": {"link_token": generate_token(10), "code": generate_code(), "direct": []},
            "audit": [],
            "result": None,
        }
        db["matches"][match_id] = match
        db["match_chat"].setdefault(match_id, [])
        st.success(f"Match #{match_id} creato.")

with tab_feed:
    st.subheader("Bacheca geo-localizzata")
    my_lat = st.number_input("La tua latitudine", value=45.4642, format="%.4f", key="my_lat")
    my_lon = st.number_input("La tua longitudine", value=9.1900, format="%.4f", key="my_lon")
    filter_sport = st.multiselect("Filtro sport", list(SPORT_ROLES.keys()))
    max_distance = st.slider("Distanza max (km)", 1, 100, 30)
    filter_comp = st.selectbox("Tipo", ["all", "competitiva", "amichevole"])
    only_open_slots = st.toggle("Solo con posti disponibili", value=True)

    cards: list[dict[str, Any]] = []
    for match in db["matches"].values():
        if match["status"] not in {"open", "closed"}:
            continue
        if match["visibility"] == "private":
            if user.username not in match["invites"]["direct"]:
                continue
        if filter_sport and match["sport"] not in filter_sport:
            continue
        if filter_comp == "competitiva" and not match["competitive"]:
            continue
        if filter_comp == "amichevole" and match["competitive"]:
            continue
        dist = haversine_km(my_lat, my_lon, match["geo"][0], match["geo"][1])
        if dist > max_distance:
            continue
        slots_left = match["max_players"] - len(match["participants"])
        if only_open_slots and slots_left <= 0:
            continue
        cards.append({"match": match, "distance": dist, "slots_left": slots_left})

    cards.sort(key=lambda x: (x["distance"], x["match"]["starts_at"]))
    for row in cards:
        m = row["match"]
        with st.container(border=True):
            st.write(
                f"**#{m['id']} {m['sport']}** · {m['city']} · {m['starts_at'].strftime('%d/%m %H:%M')} · "
                f"{m['duration']} min · {'Competitiva' if m['competitive'] else 'Amichevole'}"
            )
            st.write(f"Team: A vs B ({m['team_size']}v{m['team_size']}) | Posti: {row['slots_left']} | Distanza: {row['distance']:.1f} km")
            if m["required_roles"]:
                st.write(f"Ruoli richiesti: {m['required_roles']}")
            if st.button(f"Unisciti #{m['id']}"):
                allowed_roles = user.roles_by_sport.get(m["sport"], SPORT_ROLES[m["sport"]])
                selected_role = st.selectbox("Scegli ruolo", allowed_roles, key=f"join_role_{m['id']}")
                team = "A" if sum(p["team"] == "A" for p in m["participants"]) <= sum(p["team"] == "B" for p in m["participants"]) else "B"
                m["participants"].append({"username": user.username, "team": team, "role": selected_role})
                st.success("Entrato nella partita.")
                st.rerun()

with tab_chat:
    st.subheader("Chat")
    match_ids = [m_id for m_id, m in db["matches"].items() if any(p["username"] == user.username for p in m["participants"])]
    if match_ids:
        selected_match = st.selectbox("Chat partita", match_ids)
        for msg in db["match_chat"].get(selected_match, []):
            st.write(f"**{msg['from']}**: {msg['text']}")
        text = st.text_input("Messaggio partita")
        if st.button("Invia messaggio partita") and text:
            db["match_chat"][selected_match].append({"from": user.username, "text": text, "at": utc_now().isoformat()})
            st.success("Messaggio inviato (push simulata).")
    users = [u for u in db["users"] if u != user.username]
    if users:
        peer = st.selectbox("Chat 1-to-1", users)
        key = "::".join(sorted([user.username, peer]))
        db["direct_chat"].setdefault(key, [])
        for msg in db["direct_chat"][key]:
            st.write(f"**{msg['from']}**: {msg['text']}")
        dm = st.text_input("Messaggio diretto")
        if st.button("Invia DM") and dm:
            db["direct_chat"][key].append({"from": user.username, "text": dm, "at": utc_now().isoformat()})

with tab_results:
    st.subheader("Risultati + conferma/contestazione/modifica")
    my_matches = [m for m in db["matches"].values() if any(p["username"] == user.username for p in m["participants"])]
    for m in my_matches:
        with st.container(border=True):
            st.write(f"Match #{m['id']} · {m['sport']} · Stato: {m['status']}")
            can_submit = m["competitive"] or st.toggle(f"Inserire risultato amichevole #{m['id']}", key=f"opt_result_{m['id']}")
            if can_submit:
                a = st.number_input(f"Team A score #{m['id']}", min_value=0, value=0, key=f"a_{m['id']}")
                b = st.number_input(f"Team B score #{m['id']}", min_value=0, value=0, key=f"b_{m['id']}")
                if st.button(f"Invia risultato #{m['id']}"):
                    m["result"] = MatchResult(
                        submitted_by=user.username,
                        team_a_score=int(a),
                        team_b_score=int(b),
                        submitted_at=utc_now(),
                        expires_at=utc_now() + timedelta(hours=24),
                    )
                    m["audit"].append({"action": "submit", "by": user.username, "at": utc_now().isoformat(), "score": [a, b]})
            result = m["result"]
            if result:
                st.write(f"Risultato proposto: {result.team_a_score}-{result.team_b_score} | Stato: {result.status}")
                if result.expires_at and utc_now() > result.expires_at and result.status == "pending":
                    result.status = "null"
                    m["audit"].append({"action": "timeout_null", "at": utc_now().isoformat()})
                my_team = next((p["team"] for p in m["participants"] if p["username"] == user.username), None)
                team_has_confirmation = any(
                    next((p for p in m["participants"] if p["username"] == u and p["team"] == my_team), None)
                    for u in result.confirmations
                )
                if my_team and not team_has_confirmation and st.button(f"Conferma risultato #{m['id']}"):
                    result.confirmations.add(user.username)
                    m["audit"].append({"action": "confirm", "by": user.username, "at": utc_now().isoformat()})
                if st.button(f"Contesta risultato #{m['id']}"):
                    result.status = "null"
                    result.contested_by = user.username
                    m["audit"].append({"action": "contest", "by": user.username, "at": utc_now().isoformat()})
                if user.username == result.submitted_by and st.button(f"Modifica risultato #{m['id']}"):
                    result.submitted_at = utc_now()
                    result.expires_at = utc_now() + timedelta(hours=24)
                    result.confirmations = set()
                    result.status = "pending"
                    m["audit"].append({"action": "modify", "by": user.username, "at": utc_now().isoformat()})
                teams_confirmed = {
                    next((p["team"] for p in m["participants"] if p["username"] == u), None)
                    for u in result.confirmations
                }
                teams_confirmed.discard(None)
                if len(teams_confirmed) >= 2 and result.status == "pending":
                    result.status = "confirmed"
                    m["status"] = "completed"
                    m["audit"].append({"action": "result_confirmed", "at": utc_now().isoformat()})
                for row in m["audit"][-8:]:
                    st.caption(f"{row['at']} · {row['action']} · {row.get('by', 'system')}")

with tab_ranking:
    st.subheader("Sistema punti custom + King of the Court")
    for sport in SPORT_ROLES:
        users_with_sport = [u for u in db["users"].values() if sport in u.ratings]
        if not users_with_sport:
            continue
        leader = sorted(users_with_sport, key=lambda u: u.ratings[sport], reverse=True)[0]
        st.write(f"👑 **King of the Court ({sport})**: {leader.username} ({leader.ratings[sport]} pt)")

    st.write("### Simulatore delta punti")
    sport = st.selectbox("Sport per calcolo", [s for s in user.ratings] or list(SPORT_ROLES.keys()), key="sim_sport")
    mine = st.number_input("Rating tuo", value=float(user.ratings.get(sport, 1000.0)))
    opp = st.number_input("Rating avversario", value=1000.0)
    outcome = st.selectbox("Esito", ["W", "L"])
    delta = rating_delta(outcome, mine, opp, user.reliability)
    st.info(f"Delta deterministico configurabile: **{delta:+}** (affidabilità {user.reliability:.2f})")

    reduce_allowed = user.last_reliability_reduce is None or utc_now() - user.last_reliability_reduce > timedelta(days=30)
    if reduce_allowed:
        if st.button("Abbassa affidabilità (1 volta/mese)"):
            user.reliability_penalty = min(0.9, user.reliability_penalty + 0.2)
            user.last_reliability_reduce = utc_now()
            st.warning("Affidabilità ridotta: le variazioni punti saranno più ampie.")
    else:
        wait_days = 30 - (utc_now() - user.last_reliability_reduce).days
        st.caption(f"Riduzione affidabilità disponibile tra circa {wait_days} giorni.")

st.divider()
st.caption("Nota: prototipo funzionale in-memory (demo). Per produzione: DB persistente, geocoder, push reali, websocket e hardening sicurezza.")
