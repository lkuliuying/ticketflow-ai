from datetime import timedelta
from uuid import uuid4

import pytest
from django.utils import timezone

from identity.models import UserInfo
from system.models import FieldPermission, Menu
from tests.integration.tickets.test_viewer_contract import validate
from tickets.models import RatingTag, Status, TicketRating

RATINGS = "/api/ticket-ratings"
PAYLOAD = {
    "resolved": True,
    "satisfaction": 5,
    "handler_score": 4,
    "tags": [RatingTag.FAST, RatingTag.CLEAR],
    "comment": "处理很及时",
}


@pytest.fixture
def other_agent(users):
    agent = UserInfo.objects.create_user(username="other-technician", dept=users["agent"].dept)
    agent.roles.add(users["agent"].roles.get())
    return agent


@pytest.mark.django_db
def test_only_submitter_can_rate_visible_closed_ticket(users, other_agent, make_ticket, client_for):
    ticket = make_ticket(assignee=users["agent"], status=Status.PENDING_VERIFY)
    path = f"/api/tickets/{ticket.pk}"
    owner = client_for(users["requester"])
    for user, code in ((users["agent"], 403), (users["admin"], 403), (other_agent, 404)):
        response = client_for(user).post(f"{path}/rating", PAYLOAD, format="json")
        assert response.status_code == code, response.data
    assert owner.get(path).data["data"]["viewer"]["can_rate"] is False
    assert owner.post(f"{path}/rating", PAYLOAD, format="json").status_code == 409
    assert owner.post(f"/api/tickets/{uuid4()}/rating", PAYLOAD, format="json").status_code == 404
    assert not TicketRating.objects.exists()

    closed = owner.post(
        f"{path}/transition", {"version": ticket.version, "target_status": Status.CLOSED}, format="json"
    )
    assert closed.status_code == 200, closed.data
    detail = owner.get(path).data["data"]
    assert detail["viewer"]["can_rate"] is True
    assert detail["rating"] is None
    result = owner.post(f"{path}/rating", PAYLOAD, format="json")
    assert result.status_code == 201, result.data
    rating = result.data["data"]
    validate(rating, "ticketRating")
    assert rating | PAYLOAD == rating
    assert rating["ticket_id"] == str(ticket.pk)
    assert rating["ticket_number"] == ticket.number
    assert rating["rater_id"] == users["requester"].pk
    assert rating["handler_id"] == users["agent"].pk
    for user in users.values():
        detail = client_for(user).get(path).data["data"]
        validate(detail, "ticketDetailRating")
        assert detail["rating"] == rating
        assert detail["viewer"]["can_rate"] is False
    assert owner.post(f"{path}/rating", PAYLOAD, format="json").status_code == 409
    assert owner.patch(f"{path}/rating", {"satisfaction": 1}, format="json").status_code == 403
    assert TicketRating.objects.count() == 1
    assert TicketRating.objects.get(ticket=ticket).satisfaction == PAYLOAD["satisfaction"]


@pytest.mark.django_db
def test_rating_response_uses_the_action_field_allowlist(users, make_ticket, client_for, settings):
    settings.PERMISSION_FIELD_ENABLED = True
    requester = users["requester"]
    ticket = make_ticket(status=Status.CLOSED, assignee=users["agent"])
    menu = Menu.objects.get(name="rating:TicketFlowTickets")
    fields = FieldPermission.objects.get(menu=menu, role=requester.roles.get())
    fields.field.remove(*fields.field.filter(parent__name="tickets.ticketrating").exclude(name__in=["pk", "resolved"]))

    response = client_for(requester).post(f"/api/tickets/{ticket.pk}/rating", PAYLOAD, format="json")
    assert response.status_code == 201, response.data
    rating = TicketRating.objects.get(ticket=ticket)
    assert response.data["data"] == {"pk": str(rating.pk), "resolved": True}
    assert rating.comment == PAYLOAD["comment"]


@pytest.mark.django_db
@pytest.mark.parametrize("comment", ["", " \t\n", None])
def test_rating_stores_blank_comments_as_null(users, make_ticket, client_for, comment):
    ticket = make_ticket(status=Status.CLOSED)
    response = client_for(users["requester"]).post(
        f"/api/tickets/{ticket.pk}/rating", PAYLOAD | {"comment": comment}, format="json"
    )
    assert response.status_code == 201, response.data
    assert response.data["data"]["comment"] is None
    assert TicketRating.objects.get(ticket=ticket).comment is None


@pytest.mark.django_db
def test_rating_stays_with_handler_at_close_after_reopen_and_reassignment(users, other_agent, make_ticket, client_for):
    former_agent = users["agent"]
    ticket = make_ticket(assignee=former_agent, status=Status.PENDING_VERIFY)
    now = timezone.now()
    ticket.assignments.create(assignee=former_agent, started_at=now)
    path = f"/api/tickets/{ticket.pk}"
    owner = client_for(users["requester"])
    administrator = client_for(users["admin"])
    replacement = client_for(other_agent)

    def change(client, action, **values):
        ticket.refresh_from_db()
        response = client.post(f"{path}/{action}", {"version": ticket.version, **values}, format="json")
        assert response.status_code == 200, response.data

    change(owner, "transition", target_status=Status.CLOSED)
    rating = owner.post(f"{path}/rating", PAYLOAD, format="json")
    assert rating.status_code == 201, rating.data
    change(owner, "transition", target_status=Status.REOPENED)
    change(administrator, "assign", assignee_id=other_agent.pk)
    change(replacement, "transition", target_status=Status.IN_PROGRESS)
    change(replacement, "transition", target_status=Status.PENDING_VERIFY)
    change(owner, "transition", target_status=Status.CLOSED)

    detail = replacement.get(path).data["data"]
    assert detail["assignee_id"] == other_agent.pk
    assert detail["rating"] is None
    assert client_for(former_agent).get(path).data["data"]["rating"] == rating.data["data"]
    assert owner.get(path).data["data"]["viewer"]["can_rate"] is False
    assert owner.post(f"{path}/rating", PAYLOAD | {"handler_score": 1}, format="json").status_code == 409
    assert TicketRating.objects.get(ticket=ticket).handler_id == former_agent.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    "overrides",
    [
        {"satisfaction": 0},
        {"handler_score": 6},
        {"resolved": None},
        {"tags": ["OTHER"]},
        {"tags": ["FAST", "FAST"]},
        {"comment": "长" * 501},
    ],
)
def test_rating_payload_validation(users, make_ticket, client_for, overrides):
    ticket = make_ticket(status=Status.CLOSED)
    api = client_for(users["requester"])
    response = api.post(f"/api/tickets/{ticket.pk}/rating", PAYLOAD | overrides, format="json")
    assert response.status_code == 400, response.data
    assert not TicketRating.objects.exists()


@pytest.mark.django_db
def test_can_rate_tracks_permission_on_unassigned_closed_ticket(users, make_ticket, client_for):
    user = users["requester"]
    ticket = make_ticket(status=Status.CLOSED)
    path = f"/api/tickets/{ticket.pk}"
    api = client_for(user)
    permission = Menu.objects.get(name="rating:TicketFlowTickets")
    role = user.roles.get()
    role.menu.remove(permission)
    assert api.get(path).data["data"]["viewer"]["can_rate"] is False
    assert api.post(f"{path}/rating", PAYLOAD, format="json").status_code == 403
    role.menu.add(permission)
    assert api.get(path).data["data"]["viewer"]["can_rate"] is True
    response = api.post(f"{path}/rating", {"resolved": False, "satisfaction": 1, "handler_score": 2}, format="json")
    assert response.status_code == 201, response.data
    for field in ("handler_id", "handler_name", "comment"):
        assert response.data["data"][field] is None
    assert response.data["data"]["tags"] == []


@pytest.mark.django_db
def test_rating_menus_are_specific_to_agent_and_admin(users, client_for):
    for role, expected in (
        ("requester", set()),
        ("agent", {"TicketFlowMyRatings"}),
        ("admin", {"TicketFlowRatingStats"}),
    ):
        response = client_for(users[role]).get("/api/system/routes")
        assert response.status_code == 200, response.data
        data = response.json()
        names = {child["name"] for node in data["data"] for child in node.get("children", [])}
        assert names & {"TicketFlowMyRatings", "TicketFlowRatingStats"} == expected
        assert {"rating:TicketFlowTickets", "list:TicketFlowMyRatings"} <= set(data["auths"])
        assert ("summary:TicketFlowMyRatings" in data["auths"]) == (role != "requester")


@pytest.fixture
def rating_rows(users, other_agent, make_ticket):
    rows = []
    now = timezone.now()
    for index, (rater, handler, resolved, satisfaction, score, tags) in enumerate(
        [
            (users["requester"], users["agent"], True, 5, 4, ["FAST", "CLEAR"]),
            (other_agent, users["agent"], True, 4, 5, ["CLEAR"]),
            (users["agent"], other_agent, False, 2, 3, ["PROFESSIONAL"]),
            (users["requester"], None, False, 1, 2, []),
        ]
    ):
        ticket = make_ticket(rater, assignee=handler, status=Status.CLOSED)
        row = TicketRating.objects.create(
            ticket=ticket,
            rater=rater,
            handler=handler,
            resolved=resolved,
            satisfaction=satisfaction,
            handler_score=score,
            tags=tags,
        )
        TicketRating.objects.filter(pk=row.pk).update(created_time=now + timedelta(days=index))
        row.refresh_from_db()
        rows.append(row)
    return rows


@pytest.mark.django_db
def test_rating_list_scope_filters_and_replus_metadata(users, client_for, rating_rows):
    for role, indices in (("requester", [3, 0]), ("agent", [1, 0]), ("admin", [3, 2, 1, 0])):
        api = client_for(users[role])
        result = api.get(RATINGS, {"size": 10, "with_meta": 1})
        assert result.status_code == 200, result.data
        data = result.data["data"]
        validate(data, "ticketRatingList")
        assert data["total"] == len(indices)
        assert [row["pk"] for row in data["results"]] == [str(rating_rows[index].pk) for index in indices]
        assert {field["key"] for field in data["search_fields"]} >= {
            "handler_id",
            "satisfaction",
            "handler_score",
            "resolved",
            "created_from",
            "created_to",
        }
        assert {field["key"] for field in data["search_columns"]} >= {
            "ticket_number",
            "rater_name",
            "handler_name",
            "resolved",
            "satisfaction",
            "handler_score",
            "tags",
            "comment",
            "created_time",
        }
        for metadata in ("search-fields", "search-columns"):
            standalone = api.get(f"{RATINGS}/{metadata}")
            assert standalone.status_code == 200, standalone.data
            assert data[metadata.replace("-", "_")] == standalone.data["data"]
    admin = client_for(users["admin"])
    handlers = admin.get(RATINGS, {"handler_id": users["agent"].pk}).data["data"]["results"]
    assert [row["pk"] for row in handlers] == [str(rating_rows[index].pk) for index in (1, 0)]
    expected = rating_rows[2]
    params = {
        "handler_id": expected.handler_id,
        "satisfaction": 2,
        "handler_score": 3,
        "resolved": "false",
        "created_from": expected.created_time.isoformat(),
        "created_to": expected.created_time.isoformat(),
    }
    assert [row["pk"] for row in admin.get(RATINGS, params).data["data"]["results"]] == [str(expected.pk)]
    assert admin.get(RATINGS, {"page": 2, "size": 1}).data["data"]["results"][0]["pk"] == str(expected.pk)
    assert client_for(users["agent"]).get(RATINGS, params).data["data"]["total"] == 0
    assert admin.get(RATINGS, {"created_to": "yesterday"}).status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("invalid_handler_id", ["2.9", "2.0", "2e0", "two"])
def test_rating_handler_filter_rejects_non_integer_input(users, client_for, invalid_handler_id):
    response = client_for(users["admin"]).get(RATINGS, {"handler_id": invalid_handler_id})
    assert response.status_code == 400, response.data
    assert "handler_id" in response.data["detail"]


@pytest.mark.django_db
def test_summary_scope_weighting_and_inclusive_dates(users, client_for, rating_rows):
    summary = f"{RATINGS}/summary"
    agent = client_for(users["agent"])
    admin = client_for(users["admin"])
    assert client_for(users["requester"]).get(summary).status_code == 403
    agent_stats = agent.get(summary).data["data"]
    assert agent_stats == {
        "count": 2,
        "avg_satisfaction": 4.5,
        "avg_handler_score": 4.5,
        "resolved_rate": 1,
        "tags": {"FAST": 1, "CLEAR": 2},
    }

    full = admin.get(summary).data["data"]
    validate(full, "ticketRatingSummary")
    assert full.pop("by_handler") == [
        {"handler_id": users["agent"].pk, "handler_name": users["agent"].username, **agent_stats},
        {
            "handler_id": rating_rows[2].handler_id,
            "handler_name": rating_rows[2].handler.username,
            "count": 1,
            "avg_satisfaction": 2,
            "avg_handler_score": 3,
            "resolved_rate": 0,
            "tags": {"PROFESSIONAL": 1},
        },
        {
            "handler_id": None,
            "handler_name": None,
            "count": 1,
            "avg_satisfaction": 1,
            "avg_handler_score": 2,
            "resolved_rate": 0,
            "tags": {},
        },
    ]
    assert full == {
        "count": 4,
        "avg_satisfaction": 3,
        "avg_handler_score": 3.5,
        "resolved_rate": 0.5,
        "tags": {"FAST": 1, "PROFESSIONAL": 1, "CLEAR": 2},
    }
    boundary = rating_rows[2].created_time.isoformat()
    params = {"created_from": boundary, "created_to": boundary}
    filtered = admin.get(summary, params).data["data"]
    assert filtered["count"] == 1
    assert [row["handler_id"] for row in filtered["by_handler"]] == [rating_rows[2].handler_id]
    empty = {"count": 0, "avg_satisfaction": None, "avg_handler_score": None, "resolved_rate": None, "tags": {}}
    assert agent.get(summary, params).data["data"] == empty
    assert admin.get(summary, {"created_to": "2000-01-01T00:00:00Z"}).data["data"] == {**empty, "by_handler": []}
    assert admin.get(summary, {"created_from": "yesterday"}).status_code == 400
