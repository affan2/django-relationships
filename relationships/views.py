import json
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.http import Http404, HttpResponseRedirect, HttpResponse
from django.shortcuts import render_to_response, get_object_or_404
from django.template import RequestContext
from django.utils.http import urlquote
from django.views.generic import ListView
from django.contrib.contenttypes.models import ContentType

from .decorators import require_user
from .models import RelationshipStatus
from actstream import actions
from actstream.models import Action
from allauth.account.decorators import verified_email_required


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
    if status.login_required and not request.user.is_authenticated():
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


@verified_email_required
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
            Action.objects.all().filter(actor_content_type=ctype, actor_object_id=request.user.id, verb=u'started following', target_content_type=target_content_type, target_object_id = user.id ).delete()

        if request.is_ajax():
            return HttpResponse(json.dumps(dict(success=True)))

        try:
            if request.GET.get('next'):
                return HttpResponseRedirect(request.GET.get('next'))
            if request.POST.get('next'):
                return HttpResponseRedirect(request.POST.get('next'))
            return HttpResponseRedirect(user.get_absolute_url())
        except (AttributeError, TypeError):
            if request.META.get('HTTP_REFERER'):
                return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))

        template_name = success_template_name

    return render_to_response(template_name,
        {'to_user': user, 'status': status, 'add': add},
        context_instance=RequestContext(request))

def get_followers(request, content_type_id, object_id):
    ctype = get_object_or_404(ContentType, pk=content_type_id)
    user = get_object_or_404(ctype.model_class(), pk=object_id)
    if request.is_ajax():
        return render_to_response("relationships/friend_list_all.html", {
            "friends": user.relationships.followers,
        }, context_instance=RequestContext(request))
    else:
        return render_to_response("relationships/render_friend_list_all.html", {
            "friends": user.relationships.followers,
        }, context_instance=RequestContext(request))        

def get_follower_subset(request, content_type_id, object_id, sIndex, lIndex):
    ctype = get_object_or_404(ContentType, pk=content_type_id)
    user = get_object_or_404(ctype.model_class(), pk=object_id)
    s = (int)(""+sIndex)
    l = (int)(""+lIndex)
    if request.is_ajax():
        return render_to_response("relationships/friend_list_all.html", {
            "friends": user.relationships.followers()[s:l],
        }, context_instance=RequestContext(request))
    else:
        return render_to_response("relationships/render_friend_list_all.html", {
            "friends": user.relationships.followers()[s:l],
        }, context_instance=RequestContext(request))

def get_following(request, content_type_id, object_id):
    ctype = get_object_or_404(ContentType, pk=content_type_id)
    user = get_object_or_404(ctype.model_class(), pk=object_id)
    if request.is_ajax():
        return render_to_response("relationships/friend_list_all.html", {
            "friends": user.relationships.following,
        }, context_instance=RequestContext(request))
    else:
        return render_to_response("relationships/render_friend_list_all.html", {
            "friends": user.relationships.following,
        }, context_instance=RequestContext(request))

def get_following_subset(request, content_type_id, object_id, sIndex, lIndex):
    ctype = get_object_or_404(ContentType, pk=content_type_id)
    user = get_object_or_404(ctype.model_class(), pk=object_id)
    s = (int)(""+sIndex)
    l = (int)(""+lIndex)
    if request.is_ajax():
        return render_to_response("relationships/friend_list_all.html", {
            "friends": user.relationships.following()[s:l],
        }, context_instance=RequestContext(request))
    else:
        return render_to_response("relationships/render_friend_list_all.html", {
            "friends": user.relationships.following()[s:l],
        }, context_instance=RequestContext(request))        
