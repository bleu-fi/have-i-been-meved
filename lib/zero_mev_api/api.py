import asyncio
from typing import List
import httpx
from lib.latest_eth_block import get_latest_eth_block
from ratelimit import limits, sleep_and_retry
from lib.zero_mev_api.models import MevTransaction


API_BASE_URL = "https://data.zeromev.org/v1"
MAX_CALLS_PER_SECOND = 5


async def get_all_mev_transactions_related_to_address(address: str):
    address_from_transaction, address_to_transaction = await asyncio.gather(
        get_paginated_mev_transactions_by_address_and_key(address, "address_from"),
        get_paginated_mev_transactions_by_address_and_key(address, "address_to"),
    )
    return [*address_from_transaction, *address_to_transaction]


async def get_paginated_mev_transactions_by_address_and_key(
    address: str, params_address_key: str
) -> List[MevTransaction]:
    params = {params_address_key: address, "page": 1}
    all_data = []
    while True:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{API_BASE_URL}/mevTransactions", params=params)
        data = r.json()
        all_data.extend(data)
        if not data or len(data) < 1000:
            break
        params["page"] += 1
    return [MevTransaction(**d) for d in all_data]


async def get_all_mev_transactions_on_last_week() -> List[MevTransaction]:
    latest_eth_block_number = await get_latest_eth_block()
    eth_block_number_1_week_ago = (
        latest_eth_block_number - 46523
    )  # 1 week approx 46523 blocks

    tasks = []
    sem = asyncio.Semaphore(MAX_CALLS_PER_SECOND)

    async with httpx.AsyncClient() as client:
        for block in range(eth_block_number_1_week_ago, latest_eth_block_number, 100):
            task = asyncio.create_task(bounded_fetch(sem, client, block, 100))
            tasks.append(task)

            if len(tasks) >= MAX_CALLS_PER_SECOND:
                await asyncio.sleep(1)

        responses = await asyncio.gather(*tasks)
        return [MevTransaction(**d) for response in responses for d in response]


@sleep_and_retry
@limits(calls=MAX_CALLS_PER_SECOND, period=1)
async def fetch_all_mev_from_block(
    client: httpx.AsyncClient, block_number: int, count: int = 100
):
    url = f"{API_BASE_URL}/mevBlock"
    params = {"block_number": block_number, "count": count}
    r = await client.get(url, params=params)
    return r.json()


async def bounded_fetch(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    block_number: int,
    count: int = 100,
):
    async with sem:
        data = await fetch_all_mev_from_block(client, block_number, count)
        return data