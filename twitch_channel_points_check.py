import json

# Twitch supports channel point redemption detection through EventSub.
# Useful subscription types:
# - channel.channel_points_custom_reward_redemption.add
# - channel.channel_points_automatic_reward_redemption.add
#
# For custom rewards, Twitch also offers a polling endpoint:
# GET /helix/channel_points/custom_rewards/redemptions
# but only the app that created the reward can read those redemptions.

TARGET_REWARD_TITLE = "Hydrate"
TARGET_REWARD_ID = None


def get_matching_redemption(eventsub_payload, target_reward_title=None, target_reward_id=None):
    event = eventsub_payload.get("event", {})
    user_login = (event.get("user_login") or "").lower()
    user_name = event.get("user_name")
    reward = event.get("reward", {})
    reward_title = reward.get("title")
    reward_id = reward.get("id")

    if target_reward_id is not None and reward_id != target_reward_id:
        return None

    if target_reward_title is not None and reward_title != target_reward_title:
        return None

    if not user_login:
        return None

    return {
        "redeemed": True,
        "user_login": user_login,
        "user_name": user_name,
        "reward_title": reward_title,
        "reward_id": reward_id,
    }


def main():
    example_payload = {
        "subscription": {
            "type": "channel.channel_points_custom_reward_redemption.add",
            "version": "1",
        },
        "event": {
            "id": "example-redemption-id",
            "user_id": "12345",
            "user_login": "some_viewer",
            "user_name": "SomeViewer",
            "user_input": "hello",
            "status": "unfulfilled",
            "redeemed_at": "2026-06-20T12:00:00Z",
            "reward": {
                "id": "reward-id",
                "title": "Hydrate",
                "cost": 1000,
                "prompt": "Drink water",
            },
        },
    }

    matched = get_matching_redemption(
        example_payload,
        TARGET_REWARD_TITLE,
        TARGET_REWARD_ID,
    )

    if matched is None:
        print(json.dumps({"redeemed": False}))
    else:
        print(json.dumps(matched))


if __name__ == "__main__":
    main()
