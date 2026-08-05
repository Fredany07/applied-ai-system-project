from datetime import time

import streamlit as st

# Step 1: Establish the connection — bring the logic layer into the UI.
from pawpal_system import Owner, Pet, Task, Scheduler
from ai_care_assistant import CareAgent

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

st.title("🐾 PawPal+")

st.markdown(
    """
Welcome to PawPal+. .
"""
)


if "owner" not in st.session_state:
    st.session_state.owner = Owner(name="Jordan")

owner: Owner = st.session_state.owner

st.divider()

# --- Owner settings -------------------------------------------------------
st.subheader("Owner")
owner.name = st.text_input("Owner name", value=owner.name)
owner.set_availability(
    st.number_input(
        "Minutes available today",
        min_value=0,
        max_value=1440,
        value=owner.minutes_available or 60,
    )
)

st.divider()

# --- Step 3a: Adding a Pet ------------------------------------------------
st.subheader("Add a Pet")
col_a, col_b = st.columns(2)
with col_a:
    new_pet_name = st.text_input("Pet name", value="Mochi")
with col_b:
    new_pet_species = st.selectbox("Species", ["dog", "cat", "other"])

if st.button("Add pet"):
    # The Owner class owns this responsibility, so the UI just delegates to it.
    owner.add_pet(Pet(name=new_pet_name, species=new_pet_species))
    st.success(f"Added {new_pet_name} ({new_pet_species}).")

if not owner.pets:
    st.info("No pets yet. Add one above to start scheduling tasks.")
    st.stop()

st.write("Current pets:")
st.table(
    [{"name": pet.name, "species": pet.species, "tasks": len(pet.tasks)} for pet in owner.pets]
)

st.divider()

# --- Step 3b: Scheduling a Task ------------------------------------------
st.subheader("Add a Task")
pet_labels = [f"{i}: {pet.name}" for i, pet in enumerate(owner.pets)]
selected_pet_label = st.selectbox("For which pet?", pet_labels)
selected_pet = owner.pets[int(selected_pet_label.split(":")[0])]

col1, col2, col3 = st.columns(3)
with col1:
    task_title = st.text_input("Task title", value="Morning walk")
with col2:
    duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
with col3:
    priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)

col4, col5 = st.columns(2)
with col4:
    scheduled_time = st.time_input("Start time", value=time(8, 0))
with col5:
    recurring = st.selectbox("Repeats", ["none", "daily", "weekly"])

if st.button("Add task"):
    
    selected_pet.add_task(
        Task(
            title=task_title,
            duration_minutes=int(duration),
            priority=priority,
            scheduled_time=scheduled_time.strftime("%H:%M"),
            recurring=recurring,
        )
    )
    st.success(f"Added '{task_title}' to {selected_pet.name}.")

# --- Filter the task list by pet / status --------------------------------
st.write("All tasks:")
fcol1, fcol2 = st.columns(2)
with fcol1:
    pet_filter = st.selectbox("Filter by pet", ["All"] + [p.name for p in owner.pets])
with fcol2:
    status_filter = st.selectbox("Filter by status", ["All", "pending", "completed"])

filtered = owner.filter_tasks(
    pet_name=None if pet_filter == "All" else pet_filter,
    status=None if status_filter == "All" else status_filter,
)
if filtered:
    st.table(
        [
            {
                "title": t.title,
                "time": t.scheduled_time or "—",
                "duration_minutes": t.duration_minutes,
                "priority": t.priority,
                "repeats": t.recurring,
                "done": "✅" if t.completed else "",
            }
            for t in filtered
        ]
    )
else:
    st.info("No tasks match the current filters.")

st.divider()

# --- Step 3c: AI Care Assistant (RAG + agentic plan/act/check) -----------
# This is the Module 3 advanced AI feature: it retrieves grounded pet-care
# guidelines (RAG), proposes candidate tasks, runs them through the real
# Scheduler to check whether they fit, and revises itself up to a few times
# before handing suggestions to the owner for a final human decision.
st.subheader("🤖 AI Care Assistant")
st.caption(
    "Retrieves relevant care guidelines, drafts new tasks grounded in them, "
    "then checks the draft against your real schedule before suggesting it."
)

if "care_agent" not in st.session_state:
    st.session_state.care_agent = CareAgent()

ai_pet_label = st.selectbox("Suggest tasks for which pet?", pet_labels, key="ai_pet_select")
ai_pet = owner.pets[int(ai_pet_label.split(":")[0])]

if st.button("Suggest care tasks with AI"):
    with st.spinner("Retrieving guidelines and drafting a plan..."):
        st.session_state.ai_result = st.session_state.care_agent.suggest_tasks(ai_pet, owner)
    st.session_state.ai_result_pet_name = ai_pet.name

ai_result = st.session_state.get("ai_result")
if ai_result is not None and st.session_state.get("ai_result_pet_name") == ai_pet.name:
    mode = "live model call" if ai_result.used_llm else "offline knowledge-base fallback (no API key detected)"
    st.info(f"Mode: {mode}  •  Confidence: {ai_result.confidence:.2f}  •  Iterations: {ai_result.iterations}")

    with st.expander("Retrieved care guidelines (RAG context)"):
        for entry in ai_result.retrieved_context:
            st.markdown(f"- **{entry['category']}**: {entry['text']}")

    with st.expander("Agent reasoning trace (plan → act → check → revise)"):
        for step in ai_result.trace:
            st.markdown(f"`{step.stage}` — {step.message}")

    if ai_result.suggested_tasks:
        st.write("Suggested tasks — review and choose which to add:")
        chosen = []
        for i, task in enumerate(ai_result.suggested_tasks):
            if st.checkbox(
                f"{task.title} — {task.duration_minutes} min, {task.priority} priority",
                value=True,
                key=f"ai_suggestion_{i}",
            ):
                chosen.append(task)
        if st.button("Add selected suggestions to this pet"):
            for task in chosen:
                ai_pet.add_task(task)
            st.success(f"Added {len(chosen)} AI-suggested task(s) to {ai_pet.name}.")
            st.session_state.ai_result = None
    else:
        st.warning("The agent couldn't produce any valid suggestions this time.")

st.divider()

# --- Build the schedule ---------------------------------------------------
st.subheader("Build Schedule")
if st.button("Generate schedule"):
    scheduler = Scheduler.from_owner(owner)
    plan = scheduler.build_plan()
    if plan:
        st.write("### Today's plan")
        st.table(
            [
                {
                    "#": i,
                    "time": t.scheduled_time or "—",
                    "title": t.title,
                    "priority": t.priority,
                    "duration_minutes": t.duration_minutes,
                }
                for i, t in enumerate(plan, start=1)
            ]
        )

    conflicts = scheduler.find_conflicts()
    if conflicts:
        for earlier, later in conflicts:
            st.warning(
                f"⚠️ '{earlier.title}' ({earlier.scheduled_time}) overlaps "
                f"'{later.title}' ({later.scheduled_time})."
            )

    st.text(scheduler.explain())
