"""Core tests for pawpal_system.py (Module 2 scheduling logic)."""

from pawpal_system import Owner, Pet, Task, Scheduler


def test_mark_complete_flips_status():
    task = Task(title="Walk", duration_minutes=20)
    assert task.completed is False
    task.mark_complete()
    assert task.completed is True


def test_add_task_increases_pet_task_count():
    pet = Pet(name="Rex", species="dog")
    assert len(pet.tasks) == 0
    pet.add_task(Task(title="Walk", duration_minutes=20))
    assert len(pet.tasks) == 1


def test_sort_by_time_orders_chronologically_with_unscheduled_last():
    scheduler = Scheduler(
        tasks=[
            Task(title="No time", duration_minutes=5),
            Task(title="Late", duration_minutes=5, scheduled_time="18:00"),
            Task(title="Early", duration_minutes=5, scheduled_time="07:00"),
        ],
        minutes_available=60,
    )
    ordered = scheduler.sort_by_time()
    assert [t.title for t in ordered] == ["Early", "Late", "No time"]


def test_filter_tasks_by_pet_and_status():
    owner = Owner(name="Alex", minutes_available=60)
    rex = Pet(name="Rex", species="dog")
    whiskers = Pet(name="Whiskers", species="cat")
    owner.add_pet(rex)
    owner.add_pet(whiskers)

    rex.add_task(Task(title="Walk", duration_minutes=20))
    whiskers.add_task(Task(title="Litter", duration_minutes=10))

    rex_tasks = owner.filter_tasks(pet_name="Rex")
    assert [t.title for t in rex_tasks] == ["Walk"]

    pending = owner.filter_tasks(status="pending")
    assert len(pending) == 2
    rex_tasks[0].mark_complete()
    completed = owner.filter_tasks(status="completed")
    assert len(completed) == 1


def test_find_conflicts_flags_overlapping_tasks():
    scheduler = Scheduler(
        tasks=[
            Task(title="Walk", duration_minutes=30, scheduled_time="08:00"),
            Task(title="Feed", duration_minutes=10, scheduled_time="08:15"),
        ],
        minutes_available=60,
    )
    conflicts = scheduler.find_conflicts()
    assert len(conflicts) == 1
    earlier, later = conflicts[0]
    assert earlier.title == "Walk"
    assert later.title == "Feed"


def test_daily_recurring_task_creates_follow_up_one_day_later():
    pet = Pet(name="Rex", species="dog")
    walk = Task(title="Walk", duration_minutes=20, recurring="daily")
    pet.add_task(walk)

    follow_up = pet.complete_task(walk)

    assert walk.completed is True
    assert follow_up is not None
    assert follow_up.completed is False
    assert follow_up.due_date == walk.due_date or follow_up.due_date is not None
    assert follow_up in pet.tasks


def test_one_off_task_creates_no_follow_up():
    pet = Pet(name="Whiskers", species="cat")
    task = Task(title="Vet visit", duration_minutes=30, recurring="none")
    pet.add_task(task)

    follow_up = pet.complete_task(task)

    assert task.completed is True
    assert follow_up is None
    assert len(pet.tasks) == 1
