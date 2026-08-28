async def test_user_auth_chat_roundtrip():
    from webui.models.auths import Auths
    from webui.models.chats import Chats, ChatForm
    from webui.models.users import Users

    user = await Auths.insert_new_auth(
        email="a@b.c", password="hashed", name="甲", role="user",
    )
    assert await Users.has_users()
    assert await Users.get_num_users() == 1

    chat = await Chats.insert_new_chat(
        id="c1",
        user_id=user.id,
        form_data=ChatForm(chat={
            "title": "测试会话",
            "models": ["grain-storage-agent"],
            "history": {"messages": {}, "currentId": None},
            "messages": [],
        }),
    )
    assert chat.id == "c1"

    history = {}
    Chats.upsert_message_to_history(
        history, "m1",
        {"id": "m1", "role": "user", "content": "问题", "parentId": None,
         "childrenIds": [], "timestamp": 1},
    )
    Chats.upsert_message_to_history(
        history, "m2",
        {"id": "m2", "role": "assistant", "content": "回答",
         "parentId": "m1", "childrenIds": [], "timestamp": 2,
         "sources": [{"source": {"id": "e1", "name": "粮油储藏"}}]},
    )
    assert history["currentId"] == "m2"
    assert history["messages"]["m2"]["role"] == "assistant"
    assert history["messages"]["m2"]["sources"][0]["source"]["id"] == "e1"

    loaded = await Chats.get_chat_by_id_and_user_id("c1", user.id)
    assert loaded is not None and loaded.user_id == user.id
    assert await Chats.delete_chat_by_id_and_user_id("c1", user.id) is True
