from django.apps import apps
from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView
from django.urls import reverse_lazy

from admin.to_do.models import ToDo
from slack_bot.slack import Slack

from .emails import send_sequence_message
from .forms import ConditionCreateForm, ConditionToDoUpdateForm
from .models import Condition, ExternalMessage, PendingAdminTask, Sequence
from .serializers import (ExternalMessageSerializer,
                          PendingAdminTaskSerializer, SequenceListSerializer,
                          SequenceSerializer)
from admin.people.utils import get_templates_model, get_user_field

from django.views.generic.list import ListView
from django.views.generic.edit import UpdateView, DeleteView, CreateView
from django.views.generic.detail import DetailView
from django.views.generic.base import TemplateView, RedirectView
from django.views.generic import View

from django.http import HttpResponse
from django.http import Http404

from users.mixins import LoginRequiredMixin, AdminPermMixin

class SequenceListView(LoginRequiredMixin, AdminPermMixin, ListView):
    template_name = "templates.html"
    queryset = Sequence.objects.all().order_by("name")
    paginate_by = 10

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Sequence items"
        context["subtitle"] = ""
        context["add_action"] = reverse_lazy("sequences:create")
        return context


class SequenceCreateView(LoginRequiredMixin, AdminPermMixin, RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        seq = Sequence.objects.create(name="New sequence")
        return seq.update_url()


class SequenceView(LoginRequiredMixin, AdminPermMixin, DetailView):
    template_name = "sequence.html"
    model = Sequence

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Sequence"
        context["subtitle"] = ""
        context["object_list"] = ToDo.templates.all()
        context["condition_form"] = ConditionCreateForm()
        context["todos"] = ToDo.templates.all()
        obj = self.get_object()
        context["conditions_unconditioned"] = obj.conditions.get(condition_type=3)
        context["conditions_before_first_day"] = obj.conditions.filter(condition_type=2)
        context["conditions_after_first_day"] = obj.conditions.filter(condition_type=0)
        context["conditions_based_on_todo"] = obj.conditions.filter(condition_type=1)
        return context


class SequenceNameUpdateView(LoginRequiredMixin, AdminPermMixin, UpdateView):
    template_name = "_sequence_templates_list.html"
    model = Sequence
    fields = ['name',]
    # fake page, we don't need to report back
    success_url = '/health'


class SequenceConditionCreateView(LoginRequiredMixin, AdminPermMixin, CreateView):
    template_name = "_condition_form.html"
    model = Condition
    form_class = ConditionCreateForm
    # fake page, we don't need to report back
    success_url = '/health'

    def form_valid(self, form):
        # add condition to sequence
        sequence = get_object_or_404(Sequence, pk=self.kwargs.get("pk", -1))
        form.instance.sequence = sequence
        form.save()
        return HttpResponse(headers={'HX-Trigger': 'reload-sequence'})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["object"] = get_object_or_404(Sequence, pk=self.kwargs.get("pk", -1))
        return context

    def form_invalid(self, form):
        """If the form is invalid, render the invalid form."""
        return self.render_to_response(self.get_context_data(condition_form=form))




class SequenceTimelineDetailView(LoginRequiredMixin, AdminPermMixin, DetailView):
    template_name = "_sequence_timeline.html"
    model = Sequence

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        context["conditions_unconditioned"] = obj.conditions.get(condition_type=3)
        context["conditions_before_first_day"] = obj.conditions.filter(condition_type=2)
        context["conditions_after_first_day"] = obj.conditions.filter(condition_type=0)
        context["conditions_based_on_todo"] = obj.conditions.filter(condition_type=1)
        context["todos"] = ToDo.templates.all()
        return context


class SequenceConditionItemView(LoginRequiredMixin, AdminPermMixin, View):

    def delete(self, request, *args, **kwargs):
        condition = get_object_or_404(Condition, id=kwargs.get('pk', -1))
        templates_model = get_templates_model(kwargs.get("type", ""))
        template_item = get_object_or_404(templates_model, id=kwargs.get('template_pk', -1))
        condition.remove_item(template_item)
        return HttpResponse()

    def post(self, request, *args, **kwargs):
        condition = get_object_or_404(Condition, id=kwargs.get('pk', -1))
        templates_model = get_templates_model(kwargs.get("type", ""))
        template_item = get_object_or_404(templates_model, id=kwargs.get('template_pk', -1))
        condition.add_item(template_item)
        todos = ToDo.templates.all()
        return render(request, '_sequence_condition.html', { 'condition': condition, 'object': condition.sequence, 'todos': todos })


class SequenceConditionToDoUpdateView(LoginRequiredMixin, AdminPermMixin, UpdateView):
    template_name = "_sequence_condition.html"
    model = Condition
    form_class = ConditionToDoUpdateForm

    def get_success_url(self):
        return self.request.path

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        obj = self.get_object()
        context["condition"] = obj
        context["object"] = obj.sequence
        context["todos"] = ToDo.templates.all()
        return context


class SequenceConditionDeleteView(LoginRequiredMixin, AdminPermMixin, View):

    def delete(self, request, pk, condition_pk, *args, **kwargs):
        sequence = get_object_or_404(Sequence, id=pk)
        condition = get_object_or_404(Condition, id=condition_pk, sequence=sequence)
        if condition.condition_type == 3:
            raise Http404
        condition.delete()
        return HttpResponse()


class SequenceDeleteView(LoginRequiredMixin, AdminPermMixin, DeleteView):
    queryset = Condition.objects.all()
    success_url = reverse_lazy("sequences:list")

    def delete(self, request, *args, **kwargs):
        response = super().delete(request, *args, **kwargs)
        messages.info(request, "Sequence item has been removed")
        return response


class SequenceDefaultTemplatesView(LoginRequiredMixin, AdminPermMixin, ListView):
    template_name = "_sequence_templates_list.html"

    def get_queryset(self):
        if get_templates_model(self.request.GET.get("type", "")) is None:
            # if type does not exist, then return None
            return Sequence.objects.none()

        templates_model = get_templates_model(self.request.GET.get("type", ""))
        return templates_model.templates.all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active"] = self.request.GET.get("type", "")
        return context


# class SequenceViewSet(viewsets.ModelViewSet):
#     serializer_class = SequenceSerializer
#     queryset = Sequence.objects.all().prefetch_related("conditions", "preboarding", "to_do", "appointments", "resources")

#     def get_serializer_class(self):
#         if self.action == "list":
#             return SequenceListSerializer
#         return SequenceSerializer

#     def _get_condition_items(self, c):
#         return [
#             {"app": "to_do", "model": "ToDo", "item": "to_do", "c_model": c.to_do},
#             {
#                 "app": "resources",
#                 "model": "Resource",
#                 "item": "resources",
#                 "c_model": c.resources,
#             },
#             {
#                 "app": "sequences",
#                 "model": "PendingAdminTask",
#                 "item": "admin_tasks",
#                 "c_model": c.admin_tasks,
#             },
#             {"app": "badges", "model": "Badge", "item": "badges", "c_model": c.badges},
#             {
#                 "app": "sequences",
#                 "model": "ExternalMessage",
#                 "item": "external_messages",
#                 "c_model": c.external_messages,
#             },
#             {
#                 "app": "introductions",
#                 "model": "Introduction",
#                 "item": "introductions",
#                 "c_model": c.introductions,
#             },
#         ]

#     def _save_sequence(self, data, sequence=None):
#         # saving collection part
#         items = [
#             {
#                 "app": "to_do",
#                 "model": "ToDo",
#                 "item": "to_do",
#                 "s_model": sequence.to_do,
#             },
#             {
#                 "app": "resources",
#                 "model": "Resource",
#                 "item": "resources",
#                 "s_model": sequence.resources,
#             },
#             {
#                 "app": "preboarding",
#                 "model": "Preboarding",
#                 "item": "preboarding",
#                 "s_model": sequence.preboarding,
#             },
#         ]
#         for j in items:
#             for i in data["collection"][j["item"]]:
#                 item = apps.get_model(app_label=j["app"], model_name=j["model"]).objects.get(id=i["id"])
#                 j["s_model"].add(item)

#         # save sequence part
#         for item in data["conditions"]:
#             c = Condition.objects.create(
#                 condition_type=item["condition_type"],
#                 days=item["days"],
#                 sequence=sequence,
#             )
#             if len(item["condition_to_do"]):
#                 c.condition_to_do.set([ToDo.objects.get(id=i["id"]) for i in item["condition_to_do"]])

#             items = self._get_condition_items(c)
#             for j in items:
#                 for i in item[j["item"]]:
#                     new_item = apps.get_model(app_label=j["app"], model_name=j["model"]).objects.get(id=i["id"])
#                     j["c_model"].add(new_item)

#         return False

#     def create(self, request, *args, **kwargs):
#         serializer = self.get_serializer(data=request.data)
#         serializer.is_valid(raise_exception=True)
#         sequence = Sequence.objects.create(name=serializer.validated_data["name"])
#         data = self._save_sequence(request.data, sequence)
#         if data:
#             return Response(data, status=status.HTTP_400_BAD_REQUEST)
#         return Response(status=status.HTTP_201_CREATED)

#     def update(self, request, *args, **kwargs):
#         instance = self.get_object()
#         serializer = self.get_serializer(instance, data={"name": request.data["name"]}, partial=True)
#         serializer.is_valid(raise_exception=True)
#         self.perform_update(serializer)
#         Condition.objects.filter(sequence=instance).delete()
#         instance.to_do.clear()
#         instance.resources.clear()
#         instance.preboarding.clear()
#         instance.appointments.clear()
#         data = self._save_sequence(request.data, instance)
#         if data:
#             return Response(data, status=status.HTTP_400_BAD_REQUEST)
#         return Response(status=status.HTTP_200_OK)


# class SaveExternalMessage(APIView):
#     def post(self, request):
#         if "id" in request.data:
#             ext_message = ExternalMessage.objects.get(id=request.data["id"])
#             external_message = ExternalMessageSerializer(ext_message, data=request.data)
#         else:
#             external_message = ExternalMessageSerializer(data=request.data)
#         external_message.is_valid(raise_exception=True)
#         external_message.save()
#         return Response(external_message.data)


# class SendTestMessage(APIView):
#     def post(self, request, id):
#         ext_message = ExternalMessage.objects.select_related("send_to").prefetch_related("content_json").get(id=id)
#         if ext_message.send_via == 0:  # email
#             send_sequence_message(request.user, ext_message.email_message(), ext_message.subject)
#         elif ext_message.send_via == 1:  # slack
#             # User is not connected to slack. Needs -> employees -> 'give access'
#             if request.user.slack_channel_id == None:
#                 return Response({"slack": "not exist"}, status=status.HTTP_400_BAD_REQUEST)
#             s = Slack()
#             s.set_user(request.user)
#             blocks = []
#             for j in ext_message.content_json.all():
#                 blocks.append(j.to_slack_block(request.user))
#             s.send_message(blocks=blocks)
#         return Response()


# class SaveAdminTask(APIView):
#     def post(self, request):
#         if "id" in request.data:
#             pending_admin_task = PendingAdminTask.objects.select_related("assigned_to").get(id=request.data["id"])
#             pending_task = PendingAdminTaskSerializer(pending_admin_task, data=request.data, partial=True)
#         else:
#             pending_task = PendingAdminTaskSerializer(data=request.data)
#         pending_task.is_valid(raise_exception=True)
#         pending_task.save()
#         return Response(pending_task.data)