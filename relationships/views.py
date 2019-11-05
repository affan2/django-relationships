from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.http import Http404, HttpResponseRedirect, HttpResponse
from django.shortcuts import render,get_object_or_404
from django.template import RequestContext
from django.utils.http import urlquote
from django.views.generic import ListView
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string

from relationships.decorators import require_user
from relationships.models import RelationshipStatus
from actstream import actions
from actstream.models import Action
import json


@login_required
def relationship_redirect(request):
    return HttpResponseRedirect(reverse('relationship_list', args=[request.user.username]))


def _relationship_list(request, queryset, template_name=None, *args, **kwargs):
    return ListView(
        request=request,
        queryset=queryset,
        paginate_by=20,
        page=int(request.GET.get('page', 0)),
        template_object_name='relationship',
        template_name=template_name,
        *args,
        **kwargs
    )


def get_relationship_status_or_404(status_slug):
    try:
        return RelationshipStatus.objects.by_slug(status_slug)
    except RelationshipStatus.DoesNotExist:
        raise Http404


@require_user
def relationship_list(request, user, status_slug=None,
                      template_name='relationships/relationship_list.html'):
    if not status_slug:
        status = RelationshipStatus.objects.following()
        status_slug = status.from_slug
    else:
        # get the relationship status object we're talking about
        status = get_relationship_status_or_404(status_slug)

    # do some basic authentication
    if status.login_required and not request.user.is_authenticated:
        path = urlquote(request.get_full_path())
        tup = settings.LOGIN_URL, 'next', path
        return HttpResponseRedirect('%s?%s=%s' % tup)

    if status.private and not request.user == user:
        raise Http404

    # get a queryset of users described by this relationship
    if status.from_slug == status_slug:
        qs = user.relationships.get_relationships(status=status)
    elif status.to_slug == status_slug:
        qs = user.relationships.get_related_to(status=status)
    else:
        qs = user.relationships.get_relationships(status=status, symmetrical=True)

    ec = dict(
        from_user=user,
        status=status,
        status_slug=status_slug,
    )

    return _relationship_list(request, qs, template_name, extra_context=ec)


@login_required
@require_user
def relationship_handler(request, user, status_slug, add=True,
                         template_name='relationships/confirm.html',
                         success_template_name='relationships/success.html'):

    status = get_relationship_status_or_404(status_slug)
    is_symm = status_slug == status.symmetrical_slug

    if request.method == 'POST':
        if add:
            request.user.relationships.add(user, status, is_symm)
            actions.follow(request.user, user, actor_only=False)
        else:
            request.user.relationships.remove(user, status, is_symm)
            actions.unfollow(request.user, user)
            ctype = ContentType.objects.get_for_model(request.user)
            target_content_type = ContentType.objects.get_for_model(user)
            Action.objects.all().filter(actor_content_type=ctype, actor_object_id=request.user.id, verb='started following', target_content_type=target_content_type, target_object_id = user.id ).delete()

        if request.is_ajax():
            return HttpResponse(json.dumps(dict(success=True, count=user.relationships.followers().count())))

        if request.GET.get('next'):
            return HttpResponseRedirect(request.GET['next'])

        template_name = success_template_name

    return render(request, template_name,
        {'to_user': user, 'status': status, 'add': add})


def get_followers(request, content_type_id, object_id):
    ctype = get_object_or_404(ContentType, pk=content_type_id)
    user = get_object_or_404(ctype.model_class(), pk=object_id)
    if request.is_ajax():
        return render(request, "relationships/friend_list_all.html", {
            "profile_user": user,
            "friends": user.relationships.followers,
        })
    else:
        return render(request, "relationships/render_friend_list_all.html", {
            "friends": user.relationships.followers,
        })


def get_follower_subset(request, content_type_id, object_id, sIndex, lIndex):
    ctype = get_object_or_404(ContentType, pk=content_type_id)
    user = get_object_or_404(ctype.model_class(), pk=object_id)
    s = (int)(""+sIndex)
    l = (int)(""+lIndex)

    if s == 0:
        data_href = reverse('get_follower_subset', kwargs={ 'content_type_id':content_type_id,
                                                            'object_id':object_id,
                                                            'sIndex':0,
                                                            'lIndex': settings.MIN_FOLLOWERS_CHUNK})
        return render(request, "relationships/friend_list_all.html", {
            "profile_user": user,
            "friends": user.relationships.followers().order_by('-date_joined')[s:l],
            'is_incremental': False,
            'data_href':data_href,
            'data_chunk':settings.MIN_FOLLOWERS_CHUNK
        })

    sub_followers = user.relationships.followers().order_by('-date_joined')[s:l]

    if request.is_ajax():
        context = RequestContext(request)

        context.update({"profile_user": user,
                        'friends': sub_followers,
                        'is_incremental': True})

        template = 'relationships/friend_list_all.html'
        if sub_followers:
            ret_data = {
                'html': render_to_string(template, context=context).strip(),
                'success': True
            }
        else:
            ret_data = {
                'success': False
            }

        return HttpResponse(json.dumps(ret_data), content_type="application/json")
    else:
        return render(request, "relationships/render_friend_list_all.html", {
            "friends": sub_followers,
        })


def get_following(request, content_type_id, object_id):
    ctype = get_object_or_404(ContentType, pk=content_type_id)
    user = get_object_or_404(ctype.model_class(), pk=object_id)
    if request.is_ajax():
        return render(request, "relationships/friend_list_all.html", {
            "profile_user": user,
            "friends": user.relationships.following,
        })
    else:
        return render(request, "relationships/render_friend_list_all.html", {
            "friends": user.relationships.following,
        })


def get_following_subset(request, content_type_id, object_id, sIndex, lIndex):
    ctype = get_object_or_404(ContentType, pk=content_type_id)
    user = get_object_or_404(ctype.model_class(), pk=object_id)
    s = (int)(""+sIndex)
    l = (int)(""+lIndex)

    if s == 0:
        data_href = reverse('get_following_subset', kwargs={ 'content_type_id':content_type_id,
                                                            'object_id':object_id,
                                                            'sIndex':0,
                                                            'lIndex': settings.MIN_FOLLOWERS_CHUNK})

        return render(request, "relationships/friend_list_all.html", {
            "profile_user": user,
            "friends": user.relationships.following().order_by('-date_joined')[s:l],
            'is_incremental': False,
            'data_href':data_href
        })

    sub_following = user.relationships.following().order_by('-date_joined')[s:l]

    if request.is_ajax():
        context = RequestContext(request)

        context.update({"profile_user": user,
                        'friends': sub_following,
                        'is_incremental': True})

        template = 'relationships/friend_list_all.html'
        if sub_following:
            ret_data = {
                'html': render_to_string(template, context=context).strip(),
                'success': True
            }
        else:
            ret_data = {
                'success': False
            }

        return HttpResponse(json.dumps(ret_data), content_type="application/json")
    else:
        return render(request, "relationships/render_friend_list_all.html", {
            "friends": user.relationships.following()[s:l],
        })
