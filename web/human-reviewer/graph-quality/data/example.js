// Example data of the graph-quality review page. It is synthetic: two short segments and an invented
// merged annotation were written for this page; no text or annotation is taken from a benchmark. The
// file is a script, not JSON, so that the page also shows it when index.html is opened straight from
// disk (file://). example-segments.jsonl and example-merged.jsonl hold the same data as files, for trying
// "Import data".
window.HR_EXAMPLE = {
 "segments": [
  {
   "key": "example:ex-1:s1:1-4",
   "benchmark": "example",
   "history_id": "example",
   "segment_id": "s1",
   "kind": "session",
   "stratum": "example",
   "first_version": 1,
   "last_version": 4,
   "message_ids": [
    "X1:1",
    "X1:2",
    "X1:3",
    "X1:4"
   ],
   "context_ids": [
    "X0:1"
   ],
   "participants": [
    "Ana",
    "Ben"
   ],
   "messages": [
    {
     "message_id": "X1:1",
     "version": 0,
     "segment_id": "s1",
     "date": "2024-03-05T10:00",
     "speaker": "Ana",
     "role": "peer",
     "text": "I adopted a dog named Pip last week, and I work at a bakery."
    },
    {
     "message_id": "X1:2",
     "version": 0,
     "segment_id": "s1",
     "date": "2024-03-05T10:00",
     "speaker": "Ben",
     "role": "peer",
     "text": "Nice! Pip sounds lovely. I think I might visit Rome in May."
    },
    {
     "message_id": "X1:3",
     "version": 0,
     "segment_id": "s1",
     "date": "2024-03-05T10:00",
     "speaker": "Ana",
     "role": "peer",
     "text": "Yes, Pip is two years old."
    },
    {
     "message_id": "X1:4",
     "version": 0,
     "segment_id": "s1",
     "date": "2024-03-05T10:00",
     "speaker": "Ben",
     "role": "peer",
     "text": "Thanks for telling me. Take care!"
    }
   ],
   "context": [
    {
     "message_id": "X0:1",
     "version": 0,
     "segment_id": "s1",
     "date": "2024-03-04T18:00",
     "speaker": "Ben",
     "role": "peer",
     "text": "Hi Ana, how was your week?"
    }
   ]
  },
  {
   "key": "example:ex-2:s1:1-3",
   "benchmark": "example",
   "history_id": "example",
   "segment_id": "s1",
   "kind": "session",
   "stratum": "example",
   "first_version": 1,
   "last_version": 3,
   "message_ids": [
    "Y1:1",
    "Y1:2",
    "Y1:3"
   ],
   "context_ids": [],
   "participants": [
    "user",
    "assistant"
   ],
   "messages": [
    {
     "message_id": "Y1:1",
     "version": 0,
     "segment_id": "s1",
     "date": "2024-03-05T10:00",
     "speaker": "user",
     "role": "user",
     "text": "I need a train to Leeds on Friday, leaving after 9."
    },
    {
     "message_id": "Y1:2",
     "version": 0,
     "segment_id": "s1",
     "date": "2024-03-05T10:00",
     "speaker": "assistant",
     "role": "agent",
     "text": "There is a train at 09:30 or one at 11:15. Which do you prefer?"
    },
    {
     "message_id": "Y1:3",
     "version": 0,
     "segment_id": "s1",
     "date": "2024-03-05T10:00",
     "speaker": "user",
     "role": "user",
     "text": "The 11:15 please."
    }
   ],
   "context": []
  }
 ],
 "merged": [
  {
   "segment": "example:ex-1:s1:1-4",
   "message_id": "X1:1",
   "agreement": "both",
   "strict": true,
   "differs": [],
   "agent-A": {
    "id": "c1",
    "message_id": "X1:1",
    "subject": "Ana",
    "predicate": "adopted",
    "object": "Pip",
    "object_type": "entity",
    "speaker": "Ana",
    "function": "inform",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": "last week",
    "valid_from": null,
    "valid_until": null,
    "quote": "I adopted a dog named Pip"
   },
   "agent-B": {
    "id": "c1",
    "message_id": "X1:1",
    "subject": "Ana",
    "predicate": "adopted",
    "object": "Pip",
    "object_type": "entity",
    "speaker": "Ana",
    "function": "inform",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": "last week",
    "valid_from": null,
    "valid_until": null,
    "quote": "I adopted a dog named Pip"
   }
  },
  {
   "segment": "example:ex-1:s1:1-4",
   "message_id": "X1:1",
   "agreement": "both",
   "strict": true,
   "differs": [
    "object_type"
   ],
   "agent-A": {
    "id": "c2",
    "message_id": "X1:1",
    "subject": "Ana",
    "predicate": "worksAt",
    "object": "bakery",
    "object_type": "entity",
    "speaker": "Ana",
    "function": "inform",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "I work at a bakery"
   },
   "agent-B": {
    "id": "c2",
    "message_id": "X1:1",
    "subject": "Ana",
    "predicate": "worksAt",
    "object": "bakery",
    "object_type": "string",
    "speaker": "Ana",
    "function": "inform",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "I work at a bakery"
   }
  },
  {
   "segment": "example:ex-1:s1:1-4",
   "message_id": "X1:1",
   "agreement": "agent-B_only",
   "agent-A": null,
   "agent-B": {
    "id": "c3",
    "message_id": "X1:1",
    "subject": "Ana",
    "predicate": "owns",
    "object": "Pip",
    "object_type": "entity",
    "speaker": "Ana",
    "function": "inform",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "a dog named Pip"
   }
  },
  {
   "segment": "example:ex-1:s1:1-4",
   "message_id": "X1:2",
   "agreement": "both",
   "strict": true,
   "differs": [
    "certainty",
    "report_mode",
    "time_expression"
   ],
   "agent-A": {
    "id": "c3",
    "message_id": "X1:2",
    "subject": "Ben",
    "predicate": "plansToVisit",
    "object": "Rome",
    "object_type": "entity",
    "speaker": "Ben",
    "function": "inform",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "possible",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "I might visit Rome in May"
   },
   "agent-B": {
    "id": "c4",
    "message_id": "X1:2",
    "subject": "Ben",
    "predicate": "plansToVisit",
    "object": "Rome",
    "object_type": "entity",
    "speaker": "Ben",
    "function": "inform",
    "report_mode": "hypothetical",
    "polarity": "positive",
    "certainty": "probable",
    "derived": false,
    "correction": false,
    "time_expression": "in May",
    "valid_from": null,
    "valid_until": null,
    "quote": "I might visit Rome in May"
   }
  },
  {
   "segment": "example:ex-1:s1:1-4",
   "message_id": "X1:2",
   "agreement": "agent-A_only",
   "agent-A": {
    "id": "c4",
    "message_id": "X1:2",
    "subject": "Ben",
    "predicate": "likes",
    "object": "Pip",
    "object_type": "entity",
    "speaker": "Ben",
    "function": "inform",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "Pip sounds lovely"
   },
   "agent-B": null
  },
  {
   "segment": "example:ex-1:s1:1-4",
   "message_id": "X1:3",
   "agreement": "both",
   "strict": true,
   "differs": [],
   "agent-A": {
    "id": "c5",
    "message_id": "X1:3",
    "subject": "Pip",
    "predicate": "hasAge",
    "object": "2",
    "object_type": "integer",
    "speaker": "Ana",
    "function": "inform",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "Pip is two years old"
   },
   "agent-B": {
    "id": "c5",
    "message_id": "X1:3",
    "subject": "Pip",
    "predicate": "hasAge",
    "object": "2",
    "object_type": "integer",
    "speaker": "Ana",
    "function": "inform",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "Pip is two years old"
   }
  },
  {
   "segment": "example:ex-2:s1:1-3",
   "message_id": "Y1:1",
   "agreement": "both",
   "strict": true,
   "differs": [],
   "agent-A": {
    "id": "c1",
    "message_id": "Y1:1",
    "subject": "user's train booking",
    "predicate": "destination",
    "object": "Leeds",
    "object_type": "entity",
    "speaker": "user",
    "function": "request",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "a train to Leeds"
   },
   "agent-B": {
    "id": "c1",
    "message_id": "Y1:1",
    "subject": "user's train booking",
    "predicate": "destination",
    "object": "Leeds",
    "object_type": "entity",
    "speaker": "user",
    "function": "request",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "a train to Leeds"
   }
  },
  {
   "segment": "example:ex-2:s1:1-3",
   "message_id": "Y1:1",
   "agreement": "both",
   "strict": true,
   "differs": [],
   "agent-A": {
    "id": "c2",
    "message_id": "Y1:1",
    "subject": "user's train booking",
    "predicate": "departureDay",
    "object": "Friday",
    "object_type": "string",
    "speaker": "user",
    "function": "request",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "on Friday"
   },
   "agent-B": {
    "id": "c2",
    "message_id": "Y1:1",
    "subject": "user's train booking",
    "predicate": "departureDay",
    "object": "Friday",
    "object_type": "string",
    "speaker": "user",
    "function": "request",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "on Friday"
   }
  },
  {
   "segment": "example:ex-2:s1:1-3",
   "message_id": "Y1:2",
   "agreement": "both",
   "strict": true,
   "differs": [
    "object_type"
   ],
   "agent-A": {
    "id": "c3",
    "message_id": "Y1:2",
    "subject": "user's train booking",
    "predicate": "trainOption",
    "object": "09:30",
    "object_type": "time",
    "speaker": "assistant",
    "function": "offer",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "a train at 09:30"
   },
   "agent-B": {
    "id": "c3",
    "message_id": "Y1:2",
    "subject": "user's train booking",
    "predicate": "trainOption",
    "object": "09:30 train",
    "object_type": "entity",
    "speaker": "assistant",
    "function": "offer",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "a train at 09:30"
   }
  },
  {
   "segment": "example:ex-2:s1:1-3",
   "message_id": "Y1:3",
   "agreement": "agent-B_only",
   "agent-A": null,
   "agent-B": {
    "id": "c4",
    "message_id": "Y1:3",
    "subject": "user's train booking",
    "predicate": "trainOption",
    "object": "11:15",
    "object_type": "entity",
    "speaker": "user",
    "function": "accept",
    "report_mode": "own",
    "polarity": "positive",
    "certainty": "certain",
    "derived": false,
    "correction": false,
    "time_expression": null,
    "valid_from": null,
    "valid_until": null,
    "quote": "The 11:15"
   }
  }
 ]
};
