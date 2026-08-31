from blotibot.jobs import JobRegistry, StartResult


async def test_registry_enforces_exact_capacity_and_releases_jobs() -> None:
    jobs = JobRegistry(max_active_chats=2)
    first_result, first = await jobs.try_start(1)
    second_result, second = await jobs.try_start(2)
    third_result, third = await jobs.try_start(3)

    assert first_result is StartResult.STARTED
    assert second_result is StartResult.STARTED
    assert third_result is StartResult.AT_CAPACITY
    assert first is not None and second is not None and third is None

    await jobs.finish(1, first)
    retry_result, retry = await jobs.try_start(3)
    assert retry_result is StartResult.STARTED
    assert retry is not None


async def test_cancellation_is_scoped_to_one_chat() -> None:
    jobs = JobRegistry(max_active_chats=2)
    _, first = await jobs.try_start(10)
    _, second = await jobs.try_start(20)
    assert first is not None and second is not None

    assert await jobs.cancel(10)
    assert first.cancelled.is_set()
    assert not second.cancelled.is_set()
    assert not await jobs.cancel(30)
